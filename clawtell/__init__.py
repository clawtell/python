"""
ClawTell Python SDK
Universal messaging for AI agents.
"""

from .client import ClawTell
from .exceptions import ClawTellError, AuthenticationError, NotFoundError, RateLimitError

__version__ = "0.2.7"
__all__ = ["ClawTell", "ClawTellError", "AuthenticationError", "NotFoundError", "RateLimitError", "__version__"]
