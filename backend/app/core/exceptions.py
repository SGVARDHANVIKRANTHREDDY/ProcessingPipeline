"""
Domain core exceptions v10.

Constraint: Exceptions must be absolutely side-effect free
(no logging inside them; logging is explicitly handled by global exception handlers).
"""

class DomainError(Exception):
    """Base class for all domain-specific errors."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message)
        self.message = message
        self.context = kwargs


class NotFoundError(DomainError):
    """Raised when a requested resource is not found."""
    pass


class ValidationError(DomainError):
    """Raised when a business validation rule fails."""
    pass


class ConflictError(DomainError):
    """Raised when an operation conflicts with current state (e.g., duplicates)."""
    pass


class UnauthorizedError(DomainError):
    """Raised when authentication is required and has failed or has not yet been provided."""
    pass


class ForbiddenError(DomainError):
    """Raised when the user does not have necessary permissions for a resource."""
    pass


class DependencyError(DomainError):
    """Raised when an external dependency (S3, DB, external API) fails."""
    pass
