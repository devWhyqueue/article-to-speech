class ArticleToSpeechError(Exception):
    """Base application error."""


class ConfigurationError(ArticleToSpeechError):
    """Raised when required configuration is missing or invalid."""


class InvalidUrlError(ArticleToSpeechError):
    """Raised when a Telegram message does not contain a usable URL."""


class ArticleResolutionError(ArticleToSpeechError):
    """Raised when article resolution cannot produce a full article."""


class AuthenticationRequiredError(ArticleToSpeechError):
    """Raised when the ChatGPT browser session is not authenticated."""


class BrowserAutomationError(ArticleToSpeechError):
    """Raised for ChatGPT browser automation failures."""


class TelegramDeliveryError(ArticleToSpeechError):
    """Raised when Telegram delivery fails."""


class TelegramConflictError(TelegramDeliveryError):
    """Raised when another Telegram long-poll session is already active."""
