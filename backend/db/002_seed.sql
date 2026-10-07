-- =====================================================================
-- 002_seed.sql : SYNTHETIC demo data. Every person, plan, insurer and
-- member id below is fictional. Re-runnable (idempotent).
-- Run as OWNER:  python -m scripts.run_sql db/002_seed.sql
-- =====================================================================

SET search_path TO healthbot, public;

-- ---------------------------------------------------------------------
-- 1. Insurance plans (fictional carriers)
-- ---------------------------------------------------------------------
INSERT INTO hc_insurance_plans
    (plan_name, carrier, plan_type, monthly_premium, annual_deductible, out_of_pocket_max)
VALUES
    ('Evergreen Basic HMO',      'Evergreen Health Partners', 'HMO',             289.00, 1500.00, 6500.00),
    ('Summit Choice PPO',        'Summit Mutual',             'PPO',             412.50,  800.00, 5000.00),
    ('Lakeside Value EPO',       'Lakeside Benefits',         'EPO',             335.00, 1200.00, 6000.00),
    ('Harbor Medicare Rx Plus',  'Harbor Senior Care',        'Medicare Part D',  38.60,  590.00, 2000.00)
ON CONFLICT (plan_name) DO NOTHING;   -- skip rows that already exist

-- ---------------------------------------------------------------------
-- 2. Drug catalog
-- ---------------------------------------------------------------------
INSERT INTO hc_drugs (generic_name, brand_name, drug_class)
VALUES
    ('lisinopril',    'Zestril',  'ACE inhibitor'),
    ('atorvastatin',  'Lipitor',  'Statin'),
    ('rosuvastatin',  'Crestor',  'Statin'),
    ('metformin',     'Glucophage','Biguanide'),
    ('amlodipine',    'Norvasc',  'Calcium channel blocker'),
    ('levothyroxine', 'Synthroid','Thyroid hormone'),
    ('sertraline',    'Zoloft',   'SSRI antidepressant'),
    ('omeprazole',    'Prilosec', 'Proton pump inhibitor'),
    ('albuterol',     'ProAir',   'Bronchodilator'),
    ('apixaban',      'Eliquis',  'Anticoagulant'),
    ('empagliflozin', 'Jardiance','SGLT2 inhibitor'),
    ('semaglutide',   'Ozempic',  'GLP-1 receptor agonist'),
    ('adalimumab',    'Humira',   'TNF blocker')
ON CONFLICT (generic_name) DO NOTHING;

-- ---------------------------------------------------------------------
-- 3. Coverage: every plan x every drug.
--    Two small lookup tables (as CTEs) are joined, so we describe each fact
--    once instead of typing 13 drugs x 4 plans = 52 rows by hand:
--      drug_tiers   -> which tier each drug sits in (+ prior auth / limits)
--      copay_sched  -> what each plan charges per tier
--    NOTE: tiers are the same across plans here for simplicity; real
--    formularies differ per plan.
-- ---------------------------------------------------------------------
WITH drug_tiers (generic_name, tier, prior_auth, qty_limit) AS (
    VALUES
    ('lisinopril',    1, FALSE, '90 tablets / 90 days'),
    ('atorvastatin',  1, FALSE, '90 tablets / 90 days'),
    ('metformin',     1, FALSE, NULL),
    ('amlodipine',    1, FALSE, '90 tablets / 90 days'),
    ('sertraline',    1, FALSE, NULL),
    ('rosuvastatin',  2, FALSE, '30 tablets / 30 days'),
    ('levothyroxine', 2, FALSE, NULL),
    ('omeprazole',    2, FALSE, '30 capsules / 30 days'),
    ('albuterol',     2, FALSE, '1 inhaler / 30 days'),
    ('apixaban',      3, FALSE, '60 tablets / 30 days'),
    ('empagliflozin', 3, TRUE,  '30 tablets / 30 days'),
    ('semaglutide',   4, TRUE,  '1 pen / 28 days'),
    ('adalimumab',    5, TRUE,  '2 pens / 28 days')
),
copay_sched (plan_name, tier, copay) AS (
    VALUES
    ('Evergreen Basic HMO',     1,   5.00), ('Evergreen Basic HMO',     2,  15.00),
    ('Evergreen Basic HMO',     3,  40.00), ('Evergreen Basic HMO',     4,  70.00),
    ('Evergreen Basic HMO',     5, 150.00),
    ('Summit Choice PPO',       1,  10.00), ('Summit Choice PPO',       2,  25.00),
    ('Summit Choice PPO',       3,  50.00), ('Summit Choice PPO',       4,  80.00),
    ('Summit Choice PPO',       5, 200.00),
    ('Lakeside Value EPO',      1,   8.00), ('Lakeside Value EPO',      2,  20.00),
    ('Lakeside Value EPO',      3,  45.00), ('Lakeside Value EPO',      4,  75.00),
    ('Lakeside Value EPO',      5, 175.00),
    ('Harbor Medicare Rx Plus', 1,   0.00), ('Harbor Medicare Rx Plus', 2,  10.00),
    ('Harbor Medicare Rx Plus', 3,  35.00), ('Harbor Medicare Rx Plus', 4,  47.00),
    ('Harbor Medicare Rx Plus', 5, 100.00)
)
INSERT INTO hc_plan_drug_coverage (plan_id, drug_id, tier, copay, requires_prior_auth, quantity_limit)
SELECT p.plan_id, d.drug_id, t.tier, c.copay, t.prior_auth, t.qty_limit
FROM drug_tiers t
JOIN hc_drugs d           ON d.generic_name = t.generic_name     -- name -> drug_id
JOIN copay_sched c        ON c.tier = t.tier                     -- tier -> copay, per plan
JOIN hc_insurance_plans p ON p.plan_name = c.plan_name           -- name -> plan_id
ON CONFLICT (plan_id, drug_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. Patients (fictional; phone numbers use the reserved 555-01xx range)
-- ---------------------------------------------------------------------
INSERT INTO hc_patients
    (first_name, last_name, date_of_birth, sex, phone, member_id, plan_id, allergies)
SELECT v.first_name, v.last_name, v.dob::date, v.sex, v.phone, v.member_id,
       p.plan_id, v.allergies
FROM (VALUES
    ('Maria',   'Alvarez',   '1968-03-14', 'F', '555-0101', 'EHP-100001', 'Evergreen Basic HMO',     ARRAY['penicillin']),
    ('James',   'Okafor',    '1975-11-02', 'M', '555-0102', 'SUM-200002', 'Summit Choice PPO',       ARRAY[]::text[]),
    ('Priya',   'Raman',     '1990-07-21', 'F', '555-0103', 'LKB-300003', 'Lakeside Value EPO',      ARRAY['sulfa drugs']),
    ('Harold',  'Whitfield', '1952-01-30', 'M', '555-0104', 'HSC-400004', 'Harbor Medicare Rx Plus', ARRAY['aspirin']),
    ('Linda',   'Cho',       '1959-09-09', 'F', '555-0105', 'HSC-400005', 'Harbor Medicare Rx Plus', ARRAY[]::text[]),
    ('Daniel',  'Brooks',    '1983-05-17', 'M', '555-0106', 'SUM-200007', 'Summit Choice PPO',       ARRAY['latex']),
    ('Aisha',   'Khan',      '1996-12-04', 'F', '555-0107', 'EHP-100008', 'Evergreen Basic HMO',     ARRAY[]::text[]),
    ('Robert',  'Nguyen',    '1947-04-25', 'M', '555-0108', 'HSC-400009', 'Harbor Medicare Rx Plus', ARRAY['codeine'])
) AS v(first_name, last_name, dob, sex, phone, member_id, plan_name, allergies)
JOIN hc_insurance_plans p ON p.plan_name = v.plan_name
ON CONFLICT (member_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 5. Prescriptions. Patients are found by member_id, drugs by generic name.
--    Prescriptions have no natural unique key, so NOT EXISTS keeps re-runs safe.
-- ---------------------------------------------------------------------
INSERT INTO hc_prescriptions
    (patient_id, drug_id, dosage, frequency, quantity, refills_remaining,
     prescriber_name, status, start_date, end_date)
SELECT pt.patient_id, d.drug_id, v.dosage, v.frequency, v.quantity, v.refills,
       v.prescriber, v.status, v.start_date::date, v.end_date::date
FROM (VALUES
    ('EHP-100001', 'lisinopril',    '20 mg',  'once daily',        90, 3, 'Dr. Elena Park',   'active',       '2025-01-10', NULL),
    ('EHP-100001', 'atorvastatin',  '40 mg',  'once daily at night',90, 3, 'Dr. Elena Park',   'active',       '2025-01-10', NULL),
    ('EHP-100001', 'metformin',     '500 mg', 'twice daily',      180, 2, 'Dr. Elena Park',   'active',       '2025-03-02', NULL),
    ('SUM-200002', 'amlodipine',    '5 mg',   'once daily',        90, 5, 'Dr. Marcus Lee',   'active',       '2025-02-15', NULL),
    ('SUM-200002', 'omeprazole',    '20 mg',  'once daily',        30, 1, 'Dr. Marcus Lee',   'completed',    '2024-06-01', '2024-08-01'),
    ('LKB-300003', 'levothyroxine', '75 mcg', 'once daily, empty stomach', 90, 4, 'Dr. Sofia Marin', 'active', '2024-11-20', NULL),
    ('LKB-300003', 'sertraline',    '50 mg',  'once daily',        30, 2, 'Dr. Sofia Marin',  'active',       '2025-04-05', NULL),
    ('HSC-400004', 'apixaban',      '5 mg',   'twice daily',       60, 5, 'Dr. Anil Desai',   'active',       '2025-01-22', NULL),
    ('HSC-400004', 'rosuvastatin',  '10 mg',  'once daily',        30, 3, 'Dr. Anil Desai',   'active',       '2025-01-22', NULL),
    ('HSC-400004', 'lisinopril',    '10 mg',  'once daily',        90, 0, 'Dr. Anil Desai',   'discontinued', '2023-05-10', '2024-12-01'),
    ('HSC-400005', 'empagliflozin', '10 mg',  'once daily',        30, 2, 'Dr. Grace Tan',    'active',       '2025-05-12', NULL),
    ('HSC-400005', 'metformin',     '1000 mg','twice daily',      180, 3, 'Dr. Grace Tan',    'active',       '2024-09-01', NULL),
    ('SUM-200007', 'albuterol',     '90 mcg', 'as needed, 2 puffs', 1, 2, 'Dr. Marcus Lee',   'active',       '2025-03-18', NULL),
    ('EHP-100008', 'semaglutide',   '0.5 mg', 'once weekly',       1, 1, 'Dr. Elena Park',   'active',       '2025-06-01', NULL),
    ('HSC-400009', 'atorvastatin',  '20 mg',  'once daily',        90, 4, 'Dr. Anil Desai',   'active',       '2024-08-14', NULL),
    ('HSC-400009', 'amlodipine',    '10 mg',  'once daily',        90, 4, 'Dr. Anil Desai',   'active',       '2024-08-14', NULL)
) AS v(member_id, generic_name, dosage, frequency, quantity, refills,
       prescriber, status, start_date, end_date)
JOIN hc_patients pt ON pt.member_id    = v.member_id
JOIN hc_drugs d     ON d.generic_name  = v.generic_name
WHERE NOT EXISTS (                                   -- idempotency guard
    SELECT 1 FROM hc_prescriptions x
    WHERE x.patient_id = pt.patient_id
      AND x.drug_id    = d.drug_id
      AND x.start_date = v.start_date::date
);

-- ---------------------------------------------------------------------
-- 6. Sanity counts (shown when you run it): expect 4 / 13 / 52 / 8 / 16
-- ---------------------------------------------------------------------
SELECT (SELECT count(*) FROM hc_insurance_plans)   AS plans,
       (SELECT count(*) FROM hc_drugs)             AS drugs,
       (SELECT count(*) FROM hc_plan_drug_coverage) AS coverage,
       (SELECT count(*) FROM hc_patients)          AS patients,
       (SELECT count(*) FROM hc_prescriptions)     AS prescriptions;
