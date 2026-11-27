"""Scripted learner turns shared by the live journeys."""

from live.session import Session, Turn

TOPIC = "/dive Python list comprehensions"
CONTEXT = "I know basic Python loops. I want to read other people's code more easily."
CHARTER = (
    "Just curiosity. Core question: when to use one instead of a for loop. Skip generators for "
    "now. Search term: Python. Done when I can rewrite a loop as a comprehension. "
    "That charter looks good, please save it."
)


def dive_intake(session: Session) -> list[Turn]:
    """Run the three scoping turns that end with a saved charter."""
    return [session.turn(text) for text in (TOPIC, CONTEXT, CHARTER)]
