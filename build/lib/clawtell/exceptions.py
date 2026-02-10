"""ClawTell exceptions."""


class ClawTellError(Exception):
    """Base exception for ClawTell errors."""
    
    def __init__(self, message: str, status_code: int = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthenticationError(ClawTellError):
    """Raised when API key is invalid or missing."""
    pass


class NotFoundError(ClawTellError):
    """Raised when a resource is not found."""
    pass


class RateLimitError(ClawTellError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after
