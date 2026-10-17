from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UpdateCheckStatus(str, Enum):
    """检查更新的业务结果。"""

    UPDATE_AVAILABLE = "update_available"
    UP_TO_DATE = "up_to_date"


class UpdateProgressStage(str, Enum):
    """程序内下载的可见阶段。"""

    DOWNLOADING = "downloading"
    VERIFYING = "verifying"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True)
class AppUpdateCheckResult:
    status: UpdateCheckStatus
    current_version: str
    latest_version: str
    published_at: str
    release_notes: str
    release_url: str
    package_asset: ReleaseAsset | None = None
    expected_sha256: str = ""

    @property
    def update_available(self) -> bool:
        return self.status is UpdateCheckStatus.UPDATE_AVAILABLE


@dataclass(frozen=True)
class AppUpdateProgress:
    stage: UpdateProgressStage
    completed_bytes: int
    total_bytes: int


__all__ = [
    "AppUpdateCheckResult",
    "AppUpdateProgress",
    "ReleaseAsset",
    "UpdateCheckStatus",
    "UpdateProgressStage",
]
