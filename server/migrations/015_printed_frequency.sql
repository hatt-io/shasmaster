CREATE TABLE printed_form_frequency(normalized TEXT PRIMARY KEY, occurrences INTEGER NOT NULL);
INSERT INTO printed_form_frequency SELECT normalized,COUNT(*) FROM occurrence WHERE active=1 AND normalized<>'' GROUP BY normalized;
INSERT OR REPLACE INTO metadata(key,value) VALUES('printed_frequency_revision','1');

CREATE TRIGGER printed_frequency_insert AFTER INSERT ON occurrence WHEN new.active=1 AND new.normalized<>'' BEGIN
  INSERT INTO printed_form_frequency VALUES(new.normalized,1) ON CONFLICT(normalized) DO UPDATE SET occurrences=occurrences+1;
  UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='printed_frequency_revision';
END;

CREATE TRIGGER printed_frequency_delete AFTER DELETE ON occurrence WHEN old.active=1 AND old.normalized<>'' BEGIN
  UPDATE printed_form_frequency SET occurrences=occurrences-1 WHERE normalized=old.normalized;
  DELETE FROM printed_form_frequency WHERE normalized=old.normalized AND occurrences<=0;
  UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='printed_frequency_revision';
END;

CREATE TRIGGER printed_frequency_update AFTER UPDATE OF normalized,active ON occurrence WHEN old.normalized<>new.normalized OR old.active<>new.active BEGIN
  UPDATE printed_form_frequency SET occurrences=occurrences-1 WHERE normalized=old.normalized AND old.active=1;
  INSERT INTO printed_form_frequency SELECT new.normalized,1 WHERE new.active=1 AND new.normalized<>'' ON CONFLICT(normalized) DO UPDATE SET occurrences=occurrences+1;
  DELETE FROM printed_form_frequency WHERE normalized=old.normalized AND occurrences<=0;
  UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='printed_frequency_revision';
END;
