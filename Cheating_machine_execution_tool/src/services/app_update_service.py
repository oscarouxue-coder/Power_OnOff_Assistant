from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from src.core.github_release_client import (
    DownloadCancelled,
    DEFAULT_REPOSITORY,
    GitHubReleaseClient,
    GitHubReleaseError,
)
from src.models.app_update import (
    AppUpdateCheckResult,
    AppUpdateProgress,
    ReleaseAsset,
    UpdateCheckStatus,
    UpdateProgressStage,
)


PORTABLE_ZIP_NAME = "LineCheckAssistant_portable.zip"
PORTABLE_ZIP_SHA256_NAME = "LineCheckAssistant_portable.zip.sha256.txt"
_VERSION_PATTERN = re.compile(r"^[vV]?([0-9]+)\.([0-9]+)\.([0-9]+)$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class AppUpdateError(RuntimeError):
    """可直接展示给操作员的更新业务错误。"""


class AppUpdateCancelled(AppUpdateError):
    pass


class AppUpdateService:
    def __init__(self, client: GitHubReleaseClient | None = None) -> None:
        self.client = client or GitHubReleaseClient()

    @staticmethod
    def parse_version(version: str) -> tuple[int, int, int]:
        match = _VERSION_PATTERN.fullmatch((version or "").strip())
        if not match:
            raise AppUpdateError(
                f"版本号“{version or '(空)'}”格式无效，应为 v主版本.次版本.修订号。"
            )
        return tuple(int(value) for value in match.groups())

    @staticmethod
    def _asset_from_payload(payload: dict, expected_name: str) -> ReleaseAsset | None:
        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise AppUpdateError("GitHub 返回的附件列表格式不正确。")
        for raw_asset in assets:
            if not isinstance(raw_asset, dict) or raw_asset.get("name") != expected_name:
                continue
            url = str(raw_asset.get("browser_download_url") or "")
            parsed_url = urlsplit(url)
            if parsed_url.scheme.lower() != "https" or not parsed_url.hostname:
                raise AppUpdateError(f"发布资源 {expected_name} 不是安全的 HTTPS 地址。")
            try:
                size = max(0, int(raw_asset.get("size") or 0))
            except (TypeError, ValueError):
                size = 0
            return ReleaseAsset(expected_name, url, size)
        return None

    @staticmethod
    def _parse_sha256(text: str) -> str:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2 or not _SHA256_PATTERN.fullmatch(parts[0]):
                continue
            filename = parts[1].lstrip("* ").strip()
            if filename == PORTABLE_ZIP_NAME:
                return parts[0].lower()
        raise AppUpdateError(
            f"{PORTABLE_ZIP_SHA256_NAME} 中缺少 {PORTABLE_ZIP_NAME} 的有效 SHA256。"
        )

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AppUpdateCancelled("操作已取消。")

    def check_for_update(
        self,
        current_version: str,
        cancel_event: threading.Event | None = None,
        *,
        log: Callable[[str], None] = lambda message: None,
    ) -> AppUpdateCheckResult:
        current_key = self.parse_version(current_version)
        self._raise_if_cancelled(cancel_event)
        log(f"[检查更新] GET https://api.github.com/repos/{DEFAULT_REPOSITORY}/releases/latest")
        try:
            payload = self.client.latest_release()
        except GitHubReleaseError as exc:
            self._raise_if_cancelled(cancel_event)
            raise AppUpdateError(str(exc)) from exc
        self._raise_if_cancelled(cancel_event)

        if payload.get("draft") or payload.get("prerelease"):
            raise AppUpdateError("GitHub Latest 指向草稿或预发布版本，未作为正式更新使用。")
        latest_version = str(payload.get("tag_name") or "").strip()
        latest_key = self.parse_version(latest_version)
        common = dict(
            current_version=current_version,
            latest_version=latest_version,
            published_at=str(payload.get("published_at") or ""),
            release_notes=str(payload.get("body") or "").strip(),
            release_url=str(payload.get("html_url") or ""),
        )
        if latest_key <= current_key:
            return AppUpdateCheckResult(status=UpdateCheckStatus.UP_TO_DATE, **common)

        package_asset = self._asset_from_payload(payload, PORTABLE_ZIP_NAME)
        checksum_asset = self._asset_from_payload(payload, PORTABLE_ZIP_SHA256_NAME)
        missing = [
            name
            for name, asset in (
                (PORTABLE_ZIP_NAME, package_asset),
                (PORTABLE_ZIP_SHA256_NAME, checksum_asset),
            )
            if asset is None
        ]
        if missing:
            raise AppUpdateError("最新版本发布不完整，缺少附件：" + "、".join(missing))
        self._raise_if_cancelled(cancel_event)
        try:
            log(f"[检查更新] GET {checksum_asset.download_url}")
            checksum_text = self.client.read_text_asset(checksum_asset.download_url, cancel_event)
        except DownloadCancelled as exc:
            raise AppUpdateCancelled("检查已取消。") from exc
        except GitHubReleaseError as exc:
            self._raise_if_cancelled(cancel_event)
            raise AppUpdateError(str(exc)) from exc
        self._raise_if_cancelled(cancel_event)
        expected_sha256 = self._parse_sha256(checksum_text)
        return AppUpdateCheckResult(
            status=UpdateCheckStatus.UPDATE_AVAILABLE,
            package_asset=package_asset,
            expected_sha256=expected_sha256,
            **common,
        )

    def download_update(
        self,
        update: AppUpdateCheckResult,
        destination: Path | str,
        cancel_event: threading.Event,
        progress: Callable[[AppUpdateProgress], None] | None = None,
        *,
        overwrite: bool = False,
        log: Callable[[str], None] = lambda message: None,
    ) -> Path:
        if not update.update_available or update.package_asset is None:
            raise AppUpdateError("当前检查结果没有可下载的更新包。")
        if not _SHA256_PATTERN.fullmatch(update.expected_sha256):
            raise AppUpdateError("更新包缺少有效的 SHA256，未开始下载。")

        final_path = Path(destination)
        if final_path.suffix.lower() != ".zip":
            raise AppUpdateError("更新包必须保存为 .zip 文件。")
        if final_path.exists() and not overwrite:
            raise AppUpdateError(f"目标文件已存在：{final_path}")
        if not final_path.parent.is_dir():
            raise AppUpdateError(f"保存目录不存在：{final_path.parent}")
        part_path = final_path.with_name(
            f".{final_path.name}.{uuid.uuid4().hex}.part"
        )

        def report_download(completed: int, total: int) -> None:
            if progress is not None:
                progress(
                    AppUpdateProgress(
                        UpdateProgressStage.DOWNLOADING,
                        completed,
                        total or update.package_asset.size,
                    )
                )

        try:
            self._raise_if_cancelled(cancel_event)
            try:
                log(f"[检查更新] GET {update.package_asset.download_url}；保存到 {final_path}")
                self.client.download_asset(
                    update.package_asset.download_url,
                    part_path,
                    cancel_event,
                    report_download,
                )
            except DownloadCancelled as exc:
                raise AppUpdateCancelled("下载已取消。") from exc
            except GitHubReleaseError as exc:
                self._raise_if_cancelled(cancel_event)
                raise AppUpdateError(str(exc)) from exc
            except OSError as exc:
                raise AppUpdateError(f"无法写入更新包：{exc}") from exc

            self._raise_if_cancelled(cancel_event)
            total_size = part_path.stat().st_size
            if update.package_asset.size and total_size != update.package_asset.size:
                raise AppUpdateError("更新包大小与发布信息不一致，请重新检查更新后下载。")
            digest = hashlib.sha256()
            verified = 0
            log(f"[检查更新] 下载完成，开始 SHA256 校验：{total_size} 字节。")
            if progress is not None:
                progress(AppUpdateProgress(UpdateProgressStage.VERIFYING, 0, total_size))
            with part_path.open("rb") as source:
                while True:
                    self._raise_if_cancelled(cancel_event)
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    verified += len(chunk)
                    if progress is not None:
                        progress(
                            AppUpdateProgress(
                                UpdateProgressStage.VERIFYING,
                                verified,
                                total_size,
                            )
                        )
            if digest.hexdigest().lower() != update.expected_sha256.lower():
                raise AppUpdateError("更新包 SHA256 校验失败，未生成最终 ZIP。")
            if not zipfile.is_zipfile(part_path):
                raise AppUpdateError("更新包不是有效的 ZIP 文件，未生成最终 ZIP。")
            self._raise_if_cancelled(cancel_event)
            if final_path.exists() and not overwrite:
                raise AppUpdateError(f"目标文件已存在：{final_path}")
            try:
                # Windows rename 对已存在目标报错，避免检查后出现文件的竞争覆盖。
                if overwrite:
                    os.replace(part_path, final_path)
                else:
                    os.rename(part_path, final_path)
            except OSError as exc:
                raise AppUpdateError(f"无法保存已校验的更新包：{exc}") from exc
            return final_path
        except OSError as exc:
            raise AppUpdateError(f"更新包文件读写失败：{exc}") from exc
        finally:
            try:
                part_path.unlink(missing_ok=True)
            except OSError as exc:
                raise AppUpdateError(f"无法清理本次临时文件 {part_path}：{exc}") from exc

    def close(self) -> None:
        self.client.close()


__all__ = [
    "AppUpdateCancelled",
    "AppUpdateError",
    "AppUpdateService",
    "PORTABLE_ZIP_NAME",
    "PORTABLE_ZIP_SHA256_NAME",
]
