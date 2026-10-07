-- =====================================================================
-- 008_drug_label_sources.sql : official FDA drug labels used by "drug information mode"
-- Source: DailyMed (U.S. National Library of Medicine / FDA). All 13 URLs were downloaded on 2026-10-06
-- and verified as real PDFs (720 pages in total). Labels are public-domain U.S. government records.
-- Each label is linked to its catalog drug (drug_id) so retrieval can filter by drug.
-- Re-runnable: existing URLs are skipped.
-- Run as OWNER:  python -m scripts.run_sql db/008_drug_label_sources.sql
-- =====================================================================

SET search_path TO healthbot, public;

INSERT INTO hc_policy_sources (title, publisher, url, doc_type, description, verified_on, category, drug_id)
SELECT v.title, 'U.S. FDA label via NIH DailyMed', v.url, 'fda_label', v.description, DATE '2026-10-06',
       'drug_label', d.drug_id
FROM (VALUES
    ('ZESTRIL (lisinopril) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8&type=pdf',
     'Prescribing information. Labeler: Upsher-Smith Laboratories. DailyMed set id 838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8.',
     'lisinopril'),
    ('LIPITOR (atorvastatin calcium) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=a60cc18b-0631-4cf0-b021-9f52224ece65&type=pdf',
     'Prescribing information. Labeler: Viatris Specialty LLC. DailyMed set id a60cc18b-0631-4cf0-b021-9f52224ece65.',
     'atorvastatin'),
    ('CRESTOR (rosuvastatin) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=325a5d0e-9a72-4015-9fcd-1655fb504cee&type=pdf',
     'Prescribing information. Labeler: AstraZeneca Pharmaceuticals LP. DailyMed set id 325a5d0e-9a72-4015-9fcd-1655fb504cee.',
     'rosuvastatin'),
    ('Metformin hydrochloride tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=c82a10fa-1e8e-46b6-890a-737de3f34ee1&type=pdf',
     'Prescribing information. Labeler: Zydus Pharmaceuticals USA Inc. (generic labeler). DailyMed set id c82a10fa-1e8e-46b6-890a-737de3f34ee1.',
     'metformin'),
    ('NORVASC (amlodipine besylate) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=7367289c-b0b0-466a-83e2-558e2985c29f&type=pdf',
     'Prescribing information. Labeler: Viatris Specialty LLC. DailyMed set id 7367289c-b0b0-466a-83e2-558e2985c29f.',
     'amlodipine'),
    ('SYNTHROID (levothyroxine sodium) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=1e11ad30-1041-4520-10b0-8f9d30d30fcc&type=pdf',
     'Prescribing information. Labeler: AbbVie Inc.. DailyMed set id 1e11ad30-1041-4520-10b0-8f9d30d30fcc.',
     'levothyroxine'),
    ('ZOLOFT (sertraline hydrochloride): FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=fda754f6-d0f3-4dce-a17a-927d64f912f7&type=pdf',
     'Prescribing information. Labeler: Zoloft label as published on DailyMed. DailyMed set id fda754f6-d0f3-4dce-a17a-927d64f912f7.',
     'sertraline'),
    ('Omeprazole delayed-release capsules: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=c5af5f4b-17be-7245-b281-f27c87831242&type=pdf',
     'Prescribing information. Labeler: NorthStar Rx LLC (generic labeler). DailyMed set id c5af5f4b-17be-7245-b281-f27c87831242.',
     'omeprazole'),
    ('Albuterol sulfate HFA inhalation aerosol: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=7bb5b6dd-9105-4ee7-b205-ed79cf4b371b&type=pdf',
     'Prescribing information. Labeler: Teva Pharmaceuticals USA (maker of ProAir HFA). DailyMed set id 7bb5b6dd-9105-4ee7-b205-ed79cf4b371b.',
     'albuterol'),
    ('ELIQUIS (apixaban) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=e9481622-7cc6-418a-acb6-c5450daae9b0&type=pdf',
     'Prescribing information. Labeler: E.R. Squibb & Sons / Bristol-Myers Squibb. DailyMed set id e9481622-7cc6-418a-acb6-c5450daae9b0.',
     'apixaban'),
    ('JARDIANCE (empagliflozin) tablets: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=faf3dd6a-9cd0-39c2-0d2e-232cb3f67565&type=pdf',
     'Prescribing information. Labeler: Boehringer Ingelheim Pharmaceuticals. DailyMed set id faf3dd6a-9cd0-39c2-0d2e-232cb3f67565.',
     'empagliflozin'),
    ('OZEMPIC (semaglutide) injection: FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=adec4fd2-6858-4c99-91d4-531f5f2a2d79&type=pdf',
     'Prescribing information. Labeler: Novo Nordisk. DailyMed set id adec4fd2-6858-4c99-91d4-531f5f2a2d79.',
     'semaglutide'),
    ('HUMIRA (adalimumab): FDA prescribing information',
     'https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=608d4f0d-b19f-46d3-749a-7159aa5f933d&type=pdf',
     'Prescribing information. Labeler: AbbVie Inc.. DailyMed set id 608d4f0d-b19f-46d3-749a-7159aa5f933d.',
     'adalimumab')
) AS v(title, url, description, generic_name)
JOIN hc_drugs d ON d.generic_name = v.generic_name
ON CONFLICT (url) DO NOTHING;

-- Sanity check (expect 13 drug_label rows, each linked to a drug)
SELECT count(*) AS label_sources, count(drug_id) AS linked_to_drug FROM hc_policy_sources WHERE category = 'drug_label';
