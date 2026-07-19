"""Shared service-layer exceptions."""

from __future__ import annotations


class NotFoundError(Exception):
    """Raised when a requested database row does not exist."""


class ServiceValidationError(Exception):
    """Raised when a requested operation is invalid for domain reasons."""
