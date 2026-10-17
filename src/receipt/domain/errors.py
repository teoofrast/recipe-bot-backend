class DomainError(Exception):
    """A business rule was violated. Expected: shown to the user, not logged as a failure."""
