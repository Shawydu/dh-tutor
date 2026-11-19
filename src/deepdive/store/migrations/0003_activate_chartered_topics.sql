-- 0003_activate_chartered_topics: before V0-13, charter_write left topics in 'scoping'. Topics that
-- already have a charter are active.
UPDATE topic SET status = 'active'
WHERE status = 'scoping' AND id IN (SELECT topic_id FROM charter);
