DROP TABLE IF EXISTS word_suggestion_cache;
DROP TABLE IF EXISTS decision_evidence;
DROP TABLE IF EXISTS jastrow_prepared_entry;
DROP TABLE IF EXISTS jastrow_source_span;
DROP TABLE IF EXISTS jastrow_relation_candidate;
DROP TABLE IF EXISTS jastrow_option;
DROP TABLE IF EXISTS jastrow_lookup_form;
DELETE FROM metadata WHERE key IN ('jastrow_lookup_revision','model_revision');
DELETE FROM job WHERE id IN ('jastrow-lookup','decision-model','laya-model','jastrow-preparation');
