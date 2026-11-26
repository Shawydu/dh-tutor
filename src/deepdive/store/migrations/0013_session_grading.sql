-- 0013_session_grading: the learner can switch grading off per session (V3-03).
ALTER TABLE session ADD COLUMN grading INTEGER NOT NULL DEFAULT 1 CHECK (grading IN (0, 1));
