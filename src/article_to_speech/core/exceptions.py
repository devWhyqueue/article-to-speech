class ArticleToSpeechError(Exception):
    """Base application error."""


class ConfigurationError(ArticleToSpeechError):
    """Raised when required configuration is missing or invalid."""


class InvalidUrlError(ArticleToSpeechError):
    """Raised when a Telegram message does not contain a usable URL."""


class ArticleResolutionError(ArticleToSpeechError):
    """Raised when article resolution cannot produce a full article."""


class BrowserAutomationError(ArticleToSpeechError):
    """Raised for browser automation failures."""


class SpeechSynthesisError(ArticleToSpeechError):
    """Raised when article text cannot be synthesized into audio."""


class TelegramDeliveryError(ArticleToSpeechError):
    """Raised when Telegram delivery fails."""


class TelegramConflictError(TelegramDeliveryError):
    """Raised when another Telegram long-poll session is already active."""
