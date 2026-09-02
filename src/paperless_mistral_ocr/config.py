"""Configuration for the Mistral OCR plugin.

Read from environment variables only. A plugin must not hook into the
Paperless application configuration, which belongs to the core. Dedicated
variable names also avoid clashing with the built-in remote parser
(PAPERLESS_REMOTE_OCR_*).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from paperless_mistral_ocr.helpers import MISTRAL_DEFAULT_ENDPOINT
from paperless_mistral_ocr.helpers import MISTRAL_OCR_MODEL

#: The built-in remote parser (azureai) scores 20, Tesseract 10.
#: A higher value makes Mistral win when both are configured.
DEFAULT_SCORE: int = 30

#: Truthy spellings accepted for the boolean environment variables.
_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


def _bool_from_env(name: str, default: bool) -> bool:
    """Read a boolean environment variable, falling back to *default*."""
    raw = os.getenv(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


@dataclass(frozen=True)
class MistralConfig:
    """Settings read from the environment."""

    api_key: str | None
    endpoint: str
    model: str
    score: int
    #: Fall back to Tesseract when the API call fails.
    fallback: bool
    #: Run ocrmypdf first to deskew/rotate/clean the pages.
    preprocess: bool

    @classmethod
    def from_env(cls) -> MistralConfig:
        raw_score = os.getenv("PAPERLESS_MISTRAL_OCR_SCORE", "")
        try:
            score = int(raw_score) if raw_score.strip() else DEFAULT_SCORE
        except ValueError:
            score = DEFAULT_SCORE

        endpoint = os.getenv("PAPERLESS_MISTRAL_OCR_ENDPOINT", "").strip()
        api_key = os.getenv("PAPERLESS_MISTRAL_OCR_API_KEY", "").strip()

        return cls(
            api_key=api_key or None,
            endpoint=endpoint or MISTRAL_DEFAULT_ENDPOINT,
            model=os.getenv("PAPERLESS_MISTRAL_OCR_MODEL", "").strip()
            or MISTRAL_OCR_MODEL,
            score=score,
            fallback=_bool_from_env("PAPERLESS_MISTRAL_OCR_FALLBACK", True),
            preprocess=_bool_from_env("PAPERLESS_MISTRAL_OCR_PREPROCESS", True),
        )

    def is_valid(self) -> bool:
        """True when an API key is present.

        Without a key the parser declines in score(), so Paperless keeps
        using Tesseract instead of failing during processing.
        """
        return bool(self.api_key)
