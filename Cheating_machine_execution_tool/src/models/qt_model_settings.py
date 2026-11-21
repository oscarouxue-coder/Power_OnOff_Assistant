"""Credential-free views of the original model profile editor."""
from dataclasses import dataclass
from typing import Tuple

from src.models.ai_diagnostics import ProviderProfile


@dataclass(frozen=True)
class ModelSettingsView:
    profiles: Tuple[ProviderProfile, ...]
    profile: ProviderProfile
    context_tokens: int
    context_source: str
    draft: bool = False
    notice: str = ''
    model_ids: Tuple[str, ...] = ()
