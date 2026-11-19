-- 0002_frontier: threads not yet explored. A question from a child topic can be added to its
-- parent's frontier instead of being dug into (docs/design.md "Topic lifecycle"). A child topic
-- needs no flag: a topic with a parent_topic_id always has the two-question mini-scope.
CREATE TABLE frontier (
    topic_id    UUID NOT NULL REFERENCES topic (id),
    question_id UUID NOT NULL REFERENCES question (id),
    PRIMARY KEY (topic_id, question_id)
);

CREATE INDEX frontier_question_id ON frontier (question_id);
