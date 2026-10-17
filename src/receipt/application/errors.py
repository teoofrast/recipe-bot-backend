class ApplicationError(Exception):
    """An expected failure of a use case (not found, duplicate, external service down...)."""


class UnexpectedError(ApplicationError):
    """Anything a handler did not expect. The original exception is kept in ``__cause__``."""
