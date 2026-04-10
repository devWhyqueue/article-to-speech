from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class SupportedSource:
    slug: str
    source_name: str
    host_suffixes: tuple[str, ...]


SUPPORTED_SOURCES: tuple[SupportedSource, ...] = (
    SupportedSource("zeit", "DIE ZEIT", ("zeit.de",)),
    SupportedSource("spiegel", "DER SPIEGEL", ("spiegel.de",)),
    SupportedSource("nytimes", "The New York Times", ("nytimes.com",)),
    SupportedSource("sueddeutsche", "SZ.de", ("sueddeutsche.de", "sz.de")),
    SupportedSource("faz", "FAZ", ("faz.net",)),
    SupportedSource("spektrum", "Spektrum.de", ("spektrum.de",)),
)


def detect_supported_source(url: str) -> SupportedSource | None:
    """Return the supported source that matches the given canonical article URL."""
    host = urlparse(url).netloc.lower()
    if not host:
        return None
    for source in SUPPORTED_SOURCES:
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in source.host_suffixes):
            return source
    return None
