from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests


DEFAULT_REPOSITORY = "oscarouxue-coder/Power_OnOff_Assistant"
DEFAULT_TIMEOUT = (5, 30)
MAX_CHECKSUM_BYTES = 128 * 1024


class GitHubReleaseError(RuntimeError):
    """GitHub Release 请求失败，消息可直接展示给操作员。"""


class GitHubReleaseNotFound(GitHubReleaseError):
    pass


class GitHubRateLimitError(GitHubReleaseError):
    pass


class DownloadCancelled(RuntimeError):
    pass


class GitHubReleaseClient:
    """只负责 GitHub Release 的 HTTPS 查询和资源读取。"""

    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        *,
        session=None,
        timeout: tuple[int, int] = DEFAULT_TIMEOUT,
    ) -> None:
        self.repository = repository
        self.session = session or requests.Session()
        self.timeout = timeout
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LineCheckAssistant-UpdateClient",
        }

    def _get(self, url: str, *, stream: bool):
        try:
            # GitHub 附件会跳转到资源 CDN；每一跳都必须保持 HTTPS。
            for _ in range(6):
                parsed = urlsplit(url)
                if parsed.scheme.lower() != "https" or not parsed.hostname:
                    raise GitHubReleaseError("更新资源不是有效的 HTTPS 地址。")
                response = self.session.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=stream,
                    verify=True,
                )
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise GitHubReleaseError("更新资源重定向缺少目标地址。")
                url = urljoin(url, location)
            else:
                raise GitHubReleaseError("更新资源重定向次数过多。")
        except requests.Timeout as exc:
            raise GitHubReleaseError("连接 GitHub 超时，请检查网络后重试。") from exc
        except requests.RequestException as exc:
            raise GitHubReleaseError("无法连接 GitHub，请检查网络、代理或证书后重试。") from exc

        if response.status_code == 404:
            response.close()
            raise GitHubReleaseNotFound("版本或附件不可访问（HTTP 404），请确认公开仓库及正式发布资源。")
        if response.status_code == 429 or (
            response.status_code == 403
            and response.headers.get("X-RateLimit-Remaining") == "0"
        ):
            response.close()
            raise GitHubRateLimitError("GitHub 请求次数已达上限，请稍后重试。")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            status_code = response.status_code
            response.close()
            raise GitHubReleaseError(f"GitHub 请求失败（HTTP {status_code}）。") from exc
        return response

    def latest_release(self) -> dict:
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        response = self._get(url, stream=False)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubReleaseError("GitHub 返回的版本信息无法解析。") from exc
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise GitHubReleaseError("GitHub 返回的版本信息格式不正确。")
        return payload

    def read_text_asset(self, url: str, cancel_event: threading.Event | None = None) -> str:
        response = self._get(url, stream=True)
        content = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=8192):
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("检查已取消。")
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_CHECKSUM_BYTES:
                    raise GitHubReleaseError("校验文件异常过大，已停止读取。")
        except requests.RequestException as exc:
            raise GitHubReleaseError("读取校验文件失败，请检查网络后重试。") from exc
        finally:
            response.close()
        try:
            return bytes(content).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise GitHubReleaseError("SHA256 校验文件不是有效的 UTF-8 文本。") from exc

    def download_asset(
        self,
        url: str,
        destination: Path,
        cancel_event: threading.Event,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        if cancel_event.is_set():
            raise DownloadCancelled("下载已取消。")
        response = self._get(url, stream=True)
        try:
            try:
                total_bytes = max(0, int(response.headers.get("Content-Length", "0")))
            except (TypeError, ValueError):
                total_bytes = 0
            downloaded = 0
            with destination.open("xb") as output:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancel_event.is_set():
                        raise DownloadCancelled("下载已取消。")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total_bytes)
            return downloaded
        except requests.RequestException as exc:
            raise GitHubReleaseError("下载更新包中断或超时，请检查网络后重试。") from exc
        finally:
            response.close()

    def close(self) -> None:
        self.session.close()


__all__ = [
    "DEFAULT_REPOSITORY",
    "DownloadCancelled",
    "GitHubRateLimitError",
    "GitHubReleaseClient",
    "GitHubReleaseError",
    "GitHubReleaseNotFound",
]
