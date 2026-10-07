-- =====================================================================
-- 004_policy_sources.sql : the public PDFs the chatbot may cite.
-- Every URL was fetched on 2026-10-06 and returned HTTP 200 + application/pdf.
-- All are official U.S. government publications (CMS / Medicare.gov).
-- Re-runnable: existing URLs are skipped.
-- =====================================================================

SET search_path TO healthbot, public;

INSERT INTO hc_policy_sources (title, publisher, url, doc_type, description, verified_on)
VALUES
 ('Medicare Prescription Drug Benefit Manual, Chapter 6: Part D Drugs and Formulary Requirements',
  'CMS (Centers for Medicare & Medicaid Services)',
  'https://www.cms.gov/medicare/prescription-drug-coverage/prescriptiondrugcovcontra/downloads/part-d-benefits-manual-chapter-6.pdf',
  'formulary_rules',
  'Rules for formularies, tiering, prior authorization, step therapy and quantity limits.',
  '2026-10-06'),
 ('Final CY 2026 Part D Redesign Program Instructions',
  'CMS (Centers for Medicare & Medicaid Services)',
  'https://www.cms.gov/files/document/final-cy-2026-part-d-redesign-program-instruction.pdf',
  'cost_sharing',
  'Part D benefit phases: deductible, initial coverage cost sharing, out-of-pocket cap.',
  '2026-10-06'),
 ('Medicare & You Handbook',
  'Medicare.gov (CMS)',
  'https://www.medicare.gov/publications/10050-medicare-and-you.pdf',
  'consumer_guide',
  'Consumer-level overview of Medicare coverage, drug plans, costs, rights and appeals.',
  '2026-10-06'),
 ('Your Medicare in 2027: What''s New & Changing',
  'Medicare.gov (CMS)',
  'https://www.medicare.gov/publications/12229-your-medicare-in-2027-whats-new-and-changing.pdf',
  'consumer_guide',
  'Fact sheet on upcoming Medicare cost and coverage changes.',
  '2026-10-06')
ON CONFLICT (url) DO NOTHING;
