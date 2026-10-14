-- Compress complete records only. Views expose the original text to all readers;
-- existing IDs, indexes and foreign keys stay on the underlying storage tables.
ALTER TABLE dictionary_entry RENAME TO dictionary_entry_storage;
UPDATE dictionary_entry_storage SET raw_json=shas_pack_text(raw_json), html=shas_pack_text(html);
CREATE VIEW dictionary_entry AS SELECT id,headword,normalized,ordinal,
    shas_unpack_text(raw_json) AS raw_json,shas_unpack_text(html) AS html,revision
    FROM dictionary_entry_storage;
CREATE TRIGGER dictionary_entry_write INSTEAD OF INSERT ON dictionary_entry BEGIN
    INSERT INTO dictionary_entry_storage VALUES(NEW.id,NEW.headword,NEW.normalized,NEW.ordinal,
        shas_pack_text(NEW.raw_json),shas_pack_text(NEW.html),NEW.revision);
END;
CREATE TRIGGER dictionary_entry_remove INSTEAD OF DELETE ON dictionary_entry BEGIN
    DELETE FROM dictionary_entry_storage WHERE id=OLD.id;
END;
CREATE TRIGGER dictionary_entry_change INSTEAD OF UPDATE ON dictionary_entry BEGIN
    UPDATE dictionary_entry_storage SET id=NEW.id,headword=NEW.headword,normalized=NEW.normalized,
        ordinal=NEW.ordinal,raw_json=shas_pack_text(NEW.raw_json),html=shas_pack_text(NEW.html),
        revision=NEW.revision WHERE id=OLD.id;
END;

ALTER TABLE sense RENAME TO sense_storage;
UPDATE sense_storage SET definition_html=shas_pack_text(definition_html),raw_json=shas_pack_text(raw_json);
CREATE VIEW sense AS SELECT id,entry_id,parent_id,ordinal,
    shas_unpack_text(definition_html) AS definition_html,grammar_json,
    shas_unpack_text(raw_json) AS raw_json FROM sense_storage;
CREATE TRIGGER sense_write INSTEAD OF INSERT ON sense BEGIN
    INSERT INTO sense_storage VALUES(NEW.id,NEW.entry_id,NEW.parent_id,NEW.ordinal,
        shas_pack_text(NEW.definition_html),NEW.grammar_json,shas_pack_text(NEW.raw_json));
END;
CREATE TRIGGER sense_remove INSTEAD OF DELETE ON sense BEGIN
    DELETE FROM sense_storage WHERE id=OLD.id;
END;
CREATE TRIGGER sense_change INSTEAD OF UPDATE ON sense BEGIN
    UPDATE sense_storage SET id=NEW.id,entry_id=NEW.entry_id,parent_id=NEW.parent_id,
        ordinal=NEW.ordinal,definition_html=shas_pack_text(NEW.definition_html),
        grammar_json=NEW.grammar_json,raw_json=shas_pack_text(NEW.raw_json) WHERE id=OLD.id;
END;

ALTER TABLE jastrow_source_form RENAME TO jastrow_source_form_storage;
UPDATE jastrow_source_form_storage SET raw_json=shas_pack_text(raw_json);
CREATE VIEW jastrow_source_form AS SELECT id,form,normalized,
    shas_unpack_text(raw_json) AS raw_json,revision FROM jastrow_source_form_storage;
CREATE TRIGGER jastrow_source_form_write INSTEAD OF INSERT ON jastrow_source_form BEGIN
    INSERT INTO jastrow_source_form_storage VALUES(NEW.id,NEW.form,NEW.normalized,
        shas_pack_text(NEW.raw_json),NEW.revision);
END;
CREATE TRIGGER jastrow_source_form_remove INSTEAD OF DELETE ON jastrow_source_form BEGIN
    DELETE FROM jastrow_source_form_storage WHERE id=OLD.id;
END;
CREATE TRIGGER jastrow_source_form_change INSTEAD OF UPDATE ON jastrow_source_form BEGIN
    UPDATE jastrow_source_form_storage SET id=NEW.id,form=NEW.form,normalized=NEW.normalized,
        raw_json=shas_pack_text(NEW.raw_json),revision=NEW.revision WHERE id=OLD.id;
END;
