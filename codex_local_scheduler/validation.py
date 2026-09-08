"""Validation shared by the command line and persistence layers."""

from __future__ import annotations

import re


_SLUG = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")


def validate_slug(value: str, label: str = "slug") -> str:
    """Return a safe identifier suitable for database keys and file names."""
    if not _SLUG.fullmatch(value):
        raise ValueError(
            f"{label} must start with a lowercase letter and contain only lowercase "
            "letters, digits, and hyphens (maximum 63 characters)"
        )
    return value
