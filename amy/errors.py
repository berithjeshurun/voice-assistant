"""Exceptions shared between the host, the server and tools."""

from __future__ import annotations


class AmyError(RuntimeError):
    """Base class for Amy-specific failures."""


class HostNotStarted(AmyError):
    """The ambient host has not finished starting."""


class HostBusy(AmyError):
    """Another turn is already running; the caller should retry shortly."""
