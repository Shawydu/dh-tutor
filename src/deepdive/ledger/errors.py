class InvalidInputError(Exception):
    """Arguments that pass the schema but make no sense together.

    The server turns it into `{"error": "invalid_input", "detail": ...}`, like a schema failure.
    """
