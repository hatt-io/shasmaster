-- The user replaced dictionary suggestions with their own remembered meanings.
DROP TABLE IF EXISTS jastrow_form_vector;
DROP TABLE IF EXISTS dictionary_reference;
DROP TABLE IF EXISTS dictionary_text;
DROP TABLE IF EXISTS dictionary_material;
DROP VIEW IF EXISTS sense;
DROP TABLE IF EXISTS sense_storage;
DROP VIEW IF EXISTS dictionary_entry;
DROP TABLE IF EXISTS dictionary_entry_storage;
DROP VIEW IF EXISTS jastrow_source_form;
DROP TABLE IF EXISTS jastrow_source_form_storage;
DELETE FROM metadata WHERE key LIKE 'jastrow_%';
DELETE FROM job WHERE id LIKE 'jastrow-%';
