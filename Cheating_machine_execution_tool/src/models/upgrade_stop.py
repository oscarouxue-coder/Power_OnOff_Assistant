"""Upgrade cancellation is distinct from a device failure or success."""
from dataclasses import dataclass


@dataclass(frozen=True)
class UpgradeStoppedResult:
    message: str
    skipped: bool = False
    ok: bool = False
    stopped: bool = True


class UpgradeStopped(Exception):
    """Raised only at a cooperative, safe upgrade boundary."""

