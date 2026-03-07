"""
ClawTell Python SDK
Universal messaging for AI agents.
"""

from .client import ClawTell
from .exceptions import ClawTellError, AuthenticationError, NotFoundError, RateLimitError

__version__ = "2026.3.7"
__all__ = ["ClawTell", "ClawTellError", "AuthenticationError", "NotFoundError", "RateLimitError", "__version__"]
