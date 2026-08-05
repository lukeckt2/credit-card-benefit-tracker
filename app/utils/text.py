"""Shared text normalization utilities."""

from __future__ import annotations

import re
import unicodedata


def normalize_name(value: str) -> str:
    """Normalize a benefit/card name for deduplication.

    Applies NFKC unicode normalization, lowercases, collapses whitespace,
    and truncates to 255 characters.
    """
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized[:255]
