"""Local workbench destinations attached to actionable admission errors."""
from dataclasses import dataclass
from typing import Tuple

from src.models.capabilities import CapabilityError


@dataclass(frozen=True)
class ReviewTarget:
    page: str
    field: str = ''
    channels: Tuple[int, ...] = ()
    reference: str = ''
    project_id: str = ''


class ReviewRequired(CapabilityError):
    def __init__(self, code, message, page, field='', *, channels=(), reference='', project_id='', **details):
        super().__init__(code, message, **details)
        self.review = ReviewTarget(page, field, tuple(channels), reference, project_id)
