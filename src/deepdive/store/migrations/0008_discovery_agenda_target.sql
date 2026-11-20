-- 0008_discovery_agenda_target: a discovery may target an agenda item (a facet with no question).
-- target_type is a lookup table, so a new value is one row; no rebuild.
INSERT INTO discovery_target_type (value) VALUES ('agenda_item');
