-- 0014_charter_decision: what drives the topic, and the learner's own choice when it is a decision
-- (V3-04). NULL driver = a charter written before this. ADD COLUMN ... REFERENCES is allowed
-- because the default is NULL.
CREATE TABLE charter_driver (value TEXT PRIMARY KEY);
INSERT INTO charter_driver (value) VALUES ('decision'), ('curiosity'), ('interview'), ('other');
ALTER TABLE charter ADD COLUMN driver TEXT REFERENCES charter_driver (value);
ALTER TABLE charter ADD COLUMN decision_choice TEXT;
ALTER TABLE charter ADD COLUMN decision_reasons TEXT;
