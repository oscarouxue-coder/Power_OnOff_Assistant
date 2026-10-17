import hashlib
import io
import os
import runpy
import sys
import tempfile
import threading
import unittest
import zipfile
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.github_release_client import (
    DEFAULT_TIMEOUT, MAX_CHECKSUM_BYTES, DownloadCancelled, GitHubRateLimitError,
    GitHubReleaseClient, GitHubReleaseError, GitHubReleaseNotFound,
)
from src.models.app_update import AppUpdateCheckResult, ReleaseAsset, UpdateCheckStatus, UpdateProgressStage
from src.services.app_update_service import (
    AppUpdateCancelled, AppUpdateError, AppUpdateService, PORTABLE_ZIP_NAME, PORTABLE_ZIP_SHA256_NAME,
)


def zip_content():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("LineCheckAssistant_portable/VERSION_INFO.txt", "版本：V1.1.10")
    return stream.getvalue()


ZIP_CONTENT = zip_content()
ZIP_HASH = hashlib.sha256(ZIP_CONTENT).hexdigest()


def release_payload(version="v1.1.10"):
    return {
        "tag_name": version, "draft": False, "prerelease": False,
        "published_at": "2026-10-16T01:00:00Z", "body": "修复与新增功能",
        "html_url": "https://github.com/example/app/releases/tag/" + version,
        "assets": [
            {"name": PORTABLE_ZIP_NAME, "size": len(ZIP_CONTENT), "browser_download_url": "https://github.com/example/portable.zip"},
            {"name": PORTABLE_ZIP_SHA256_NAME, "size": 100, "browser_download_url": "https://github.com/example/checksum.txt"},
        ],
    }


def update_result():
    return AppUpdateCheckResult(
        status=UpdateCheckStatus.UPDATE_AVAILABLE, current_version="V1.1.4", latest_version="v1.1.10",
        published_at="2026-10-16", release_notes="改动", release_url="https://github.com/example/app/releases",
        package_asset=ReleaseAsset(PORTABLE_ZIP_NAME, "https://github.com/example/portable.zip", len(ZIP_CONTENT)),
        expected_sha256=ZIP_HASH,
    )


def response(status=200, *, chunks=(), headers=None, payload=None):
    item = Mock(status_code=status, headers=headers or {})
    item.iter_content.return_value = iter(chunks)
    item.json.return_value = payload
    if status >= 400:
        item.raise_for_status.side_effect = requests.HTTPError(str(status))
    return item


class AppUpdateModelCompatibilityTests(unittest.TestCase):
    def test_models_support_python39_dataclass_and_remain_frozen(self):
        # 在较新的 Python 上也使用 3.9 的参数签名，防止再次引入 slots 等新参数。
        def python39_dataclass(cls=None, *, init=True, repr=True, eq=True,
                               order=False, unsafe_hash=False, frozen=False):
            return dataclass(cls, init=init, repr=repr, eq=eq, order=order,
                             unsafe_hash=unsafe_hash, frozen=frozen)

        model_path = Path(__file__).resolve().parents[1] / "src/models/app_update.py"
        with patch("dataclasses.dataclass", python39_dataclass):
            models = runpy.run_path(str(model_path))
        asset = models["ReleaseAsset"]("package.zip", "https://example.com/package.zip", 123)
        result = models["AppUpdateCheckResult"](
            models["UpdateCheckStatus"].UPDATE_AVAILABLE,
            "V1.2.1", "V1.2.2", "2026-10-17", "更新", "https://example.com/release",
        )
        progress = models["AppUpdateProgress"](models["UpdateProgressStage"].DOWNLOADING, 1, 123)
        self.assertTrue(result.update_available)
        self.assertIsNone(result.package_asset)
        self.assertEqual(result.expected_sha256, "")
        self.assertEqual(replace(asset, size=456).size, 456)
        for model, field in ((asset, "size"), (result, "latest_version"), (progress, "completed_bytes")):
            with self.subTest(model=type(model).__name__), self.assertRaises(FrozenInstanceError):
                setattr(model, field, None)


class GitHubReleaseClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = GitHubReleaseClient(session=self.session)

    def test_latest_request_is_public_https_verified_and_has_finite_timeouts(self):
        item = response(payload=release_payload())
        self.session.get.return_value = item
        self.assertEqual(self.client.latest_release()["tag_name"], "v1.1.10")
        args, kwargs = self.session.get.call_args
        self.assertEqual(args[0], "https://api.github.com/repos/oscarouxue-coder/Power_OnOff_Assistant/releases/latest")
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["timeout"], DEFAULT_TIMEOUT)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("Authorization", kwargs["headers"])
        item.close.assert_called_once()

    def test_https_cdn_redirect_is_followed_and_both_responses_are_closed(self):
        first = response(302, headers={"Location": "https://release-assets.githubusercontent.com/file"})
        last = response(payload={"tag_name": "v1.0.0"})
        self.session.get.side_effect = [first, last]
        self.client.latest_release()
        self.assertEqual(self.session.get.call_count, 2)
        first.close.assert_called_once()
        last.close.assert_called_once()

    def test_redirect_to_plain_http_is_rejected_before_request(self):
        first = response(302, headers={"Location": "http://example.invalid/file"})
        self.session.get.return_value = first
        with self.assertRaisesRegex(GitHubReleaseError, "HTTPS"):
            self.client.latest_release()
        self.assertEqual(self.session.get.call_count, 1)
        first.close.assert_called_once()

    def test_redirect_without_location_and_redirect_loop_fail(self):
        self.session.get.return_value = response(302)
        with self.assertRaisesRegex(GitHubReleaseError, "缺少目标"):
            self.client.latest_release()
        self.session.get.return_value = response(302, headers={"Location": "/again"})
        with self.assertRaisesRegex(GitHubReleaseError, "次数过多"):
            self.client.latest_release()

    def test_unavailable_or_missing_release_is_a_failure(self):
        item = response(404)
        self.session.get.return_value = item
        with self.assertRaises(GitHubReleaseNotFound):
            self.client.latest_release()
        item.close.assert_called_once()

    def test_rate_limit_and_server_errors_are_distinct_failures(self):
        for status, headers, expected in (
            (403, {"X-RateLimit-Remaining": "0"}, GitHubRateLimitError),
            (429, {}, GitHubRateLimitError), (500, {}, GitHubReleaseError),
        ):
            with self.subTest(status=status):
                item = response(status, headers=headers)
                self.session.get.return_value = item
                with self.assertRaises(expected):
                    self.client.latest_release()
                item.close.assert_called_once()

    def test_timeout_and_tls_failure_are_chinese_errors(self):
        for exception, text in ((requests.Timeout(), "超时"), (requests.exceptions.SSLError(), "证书")):
            self.session.get.side_effect = exception
            with self.assertRaisesRegex(GitHubReleaseError, text):
                self.client.latest_release()

    def test_malformed_json_or_non_object_release_is_rejected(self):
        item = response()
        item.json.side_effect = ValueError("invalid")
        self.session.get.return_value = item
        with self.assertRaisesRegex(GitHubReleaseError, "无法解析"):
            self.client.latest_release()
        item.json.side_effect = None
        item.json.return_value = []
        with self.assertRaisesRegex(GitHubReleaseError, "格式不正确"):
            self.client.latest_release()

    def test_checksum_text_is_bounded_and_response_is_closed_on_failure(self):
        item = response(chunks=[b"a" * (MAX_CHECKSUM_BYTES + 1)])
        self.session.get.return_value = item
        with self.assertRaisesRegex(GitHubReleaseError, "过大"):
            self.client.read_text_asset("https://github.com/checksum")
        item.close.assert_called_once()

    def test_checksum_decodes_bom_and_rejects_non_text(self):
        self.session.get.return_value = response(chunks=[b"\xef\xbb\xbf" + ZIP_HASH.encode()])
        self.assertEqual(self.client.read_text_asset("https://github.com/checksum"), ZIP_HASH)
        self.session.get.return_value = response(chunks=[b"\xff"])
        with self.assertRaisesRegex(GitHubReleaseError, "UTF-8"):
            self.client.read_text_asset("https://github.com/checksum")

    def test_core_streams_to_exclusive_file_and_reports_progress(self):
        item = response(chunks=[b"ab", b"", b"cd"], headers={"Content-Length": "4"})
        self.session.get.return_value = item
        progress = Mock()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "download.part"
            self.assertEqual(self.client.download_asset("https://github.com/zip", path, threading.Event(), progress), 4)
            self.assertEqual(path.read_bytes(), b"abcd")
            self.assertEqual(progress.call_args.args, (4, 4))
        item.close.assert_called_once()

    def test_core_cancel_before_start_does_not_open_network_or_file(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(DownloadCancelled):
            self.client.download_asset("https://github.com/zip", Path("unused"), event)
        self.session.get.assert_not_called()

    def test_core_stream_failure_closes_response(self):
        item = response()
        item.iter_content.side_effect = requests.ConnectionError()
        self.session.get.return_value = item
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(GitHubReleaseError, "中断或超时"):
                self.client.download_asset("https://github.com/zip", Path(folder) / "part", threading.Event())
        item.close.assert_called_once()


class AppUpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.latest_release.return_value = release_payload()
        self.client.read_text_asset.return_value = f"{ZIP_HASH.upper()} *{PORTABLE_ZIP_NAME}\n"
        self.service = AppUpdateService(self.client)

    def test_numeric_comparison_handles_multi_digit_patch_and_version_prefix(self):
        result = self.service.check_for_update("V1.1.9")
        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "v1.1.10")
        self.assertEqual(result.expected_sha256, ZIP_HASH)
        self.assertEqual(result.release_notes, "修复与新增功能")

    def test_same_or_older_remote_never_prompts_downgrade_or_reads_checksum(self):
        for remote in ("v1.1.4", "v1.0.99"):
            self.client.latest_release.return_value = release_payload(remote)
            result = self.service.check_for_update("V1.1.4")
            self.assertIs(result.status, UpdateCheckStatus.UP_TO_DATE)
        self.client.read_text_asset.assert_not_called()

    def test_invalid_current_version_stops_before_request(self):
        for version in ("未标注版本", "", "1.2", "1.2.3-rc1", "１.2.3"):
            with self.subTest(version=version), self.assertRaisesRegex(AppUpdateError, "格式无效"):
                self.service.check_for_update(version)
        self.client.latest_release.assert_not_called()

    def test_invalid_remote_version_is_failure(self):
        self.client.latest_release.return_value = release_payload("latest")
        with self.assertRaisesRegex(AppUpdateError, "格式无效"):
            self.service.check_for_update("V1.1.4")

    def test_draft_and_prerelease_are_not_offered(self):
        for flag in ("draft", "prerelease"):
            payload = release_payload()
            payload[flag] = True
            self.client.latest_release.return_value = payload
            with self.assertRaisesRegex(AppUpdateError, "未作为正式更新"):
                self.service.check_for_update("V1.1.4")
        self.client.read_text_asset.assert_not_called()

    def test_missing_each_required_asset_is_incomplete_release(self):
        for index, name in ((0, PORTABLE_ZIP_NAME), (1, PORTABLE_ZIP_SHA256_NAME)):
            payload = release_payload()
            payload["assets"].pop(index)
            self.client.latest_release.return_value = payload
            with self.assertRaises(AppUpdateError) as context:
                self.service.check_for_update("V1.1.4")
            self.assertIn(name, str(context.exception))
        self.client.read_text_asset.assert_not_called()

    def test_non_https_asset_and_malformed_asset_list_fail(self):
        payload = release_payload()
        payload["assets"][0]["browser_download_url"] = "http://example.invalid/file"
        self.client.latest_release.return_value = payload
        with self.assertRaisesRegex(AppUpdateError, "HTTPS"):
            self.service.check_for_update("V1.1.4")
        payload["assets"] = "wrong"
        with self.assertRaisesRegex(AppUpdateError, "附件列表"):
            self.service.check_for_update("V1.1.4")

    def test_checksum_must_identify_the_exact_zip(self):
        for text in (ZIP_HASH, f"{ZIP_HASH} *other.zip", "invalid", f"{'a' * 63} *{PORTABLE_ZIP_NAME}"):
            self.client.read_text_asset.return_value = text
            with self.subTest(text=text), self.assertRaisesRegex(AppUpdateError, "有效 SHA256"):
                self.service.check_for_update("V1.1.4")

    def test_404_rate_limit_timeout_propagate_as_failure(self):
        for exception in (GitHubReleaseNotFound("没有发布"), GitHubRateLimitError("已限流"), GitHubReleaseError("超时")):
            self.client.latest_release.side_effect = exception
            with self.assertRaisesRegex(AppUpdateError, str(exception)):
                self.service.check_for_update("V1.1.4")

    def test_cancel_before_and_after_release_prevents_followup_request(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(AppUpdateCancelled):
            self.service.check_for_update("V1.1.4", event)
        self.client.latest_release.assert_not_called()
        event.clear()
        self.client.latest_release.side_effect = lambda: (event.set(), release_payload())[1]
        with self.assertRaises(AppUpdateCancelled):
            self.service.check_for_update("V1.1.4", event)
        self.client.read_text_asset.assert_not_called()

    def test_cancel_during_checksum_read_is_cancelled_result(self):
        self.client.read_text_asset.side_effect = DownloadCancelled()
        with self.assertRaises(AppUpdateCancelled):
            self.service.check_for_update("V1.1.4", threading.Event())

    def test_check_logs_actual_release_and_checksum_requests(self):
        log = Mock()
        self.service.check_for_update("V1.1.4", log=log)
        self.assertIn("/releases/latest", log.call_args_list[0].args[0])
        self.assertIn("https://github.com/example/checksum.txt", log.call_args_list[1].args[0])


class AppUpdateDownloadTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.download_asset.side_effect = self.write_download
        self.service = AppUpdateService(self.client)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.destination = Path(self.folder.name) / "LineCheckAssistant_v1.1.10.zip"
        self.event = threading.Event()

    def write_download(self, url, path, event, progress):
        with path.open("xb") as output:
            output.write(ZIP_CONTENT)
        progress(len(ZIP_CONTENT), len(ZIP_CONTENT))
        return len(ZIP_CONTENT)

    def assert_no_parts(self):
        self.assertFalse(list(self.destination.parent.glob("*.part")))

    def test_success_finalizes_only_verified_zip_and_reports_both_phases(self):
        progress = Mock()
        log = Mock()
        path = self.service.download_update(update_result(), self.destination, self.event, progress, log=log)
        self.assertEqual(path, self.destination)
        self.assertEqual(path.read_bytes(), ZIP_CONTENT)
        stages = {item.args[0].stage for item in progress.call_args_list}
        self.assertEqual(stages, {UpdateProgressStage.DOWNLOADING, UpdateProgressStage.VERIFYING})
        self.assertIn("GET https://github.com/example/portable.zip", log.call_args_list[0].args[0])
        self.assert_no_parts()

    def test_existing_file_is_preserved_without_overwrite_permission(self):
        self.destination.write_bytes(b"old")
        with self.assertRaisesRegex(AppUpdateError, "已存在"):
            self.service.download_update(update_result(), self.destination, self.event)
        self.client.download_asset.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b"old")

    def test_confirmed_overwrite_replaces_only_after_success(self):
        self.destination.write_bytes(b"old")
        self.service.download_update(update_result(), self.destination, self.event, overwrite=True)
        self.assertEqual(self.destination.read_bytes(), ZIP_CONTENT)
        self.assert_no_parts()

    def test_hash_mismatch_preserves_existing_target_and_cleans_only_own_part(self):
        self.destination.write_bytes(b"old")
        unrelated = self.destination.parent / "unrelated.part"
        unrelated.write_bytes(b"keep")
        broken = replace(update_result(), expected_sha256="0" * 64)
        with self.assertRaisesRegex(AppUpdateError, "SHA256 校验失败"):
            self.service.download_update(broken, self.destination, self.event, overwrite=True)
        self.assertEqual(self.destination.read_bytes(), b"old")
        self.assertEqual(list(self.destination.parent.glob("*.part")), [unrelated])

    def test_truncated_download_fails_size_check(self):
        self.client.download_asset.side_effect = lambda url, path, event, progress: path.write_bytes(b"partial")
        with self.assertRaisesRegex(AppUpdateError, "大小"):
            self.service.download_update(update_result(), self.destination, self.event)
        self.assertFalse(self.destination.exists())
        self.assert_no_parts()

    def test_hash_correct_non_zip_is_still_rejected(self):
        text = b"not a zip"
        self.client.download_asset.side_effect = lambda url, path, event, progress: path.write_bytes(text)
        update = replace(update_result(), package_asset=replace(update_result().package_asset, size=len(text)), expected_sha256=hashlib.sha256(text).hexdigest())
        with self.assertRaisesRegex(AppUpdateError, "有效的 ZIP"):
            self.service.download_update(update, self.destination, self.event)
        self.assert_no_parts()

    def test_cancel_before_download_does_not_request_or_touch_target(self):
        self.event.set()
        with self.assertRaises(AppUpdateCancelled):
            self.service.download_update(update_result(), self.destination, self.event)
        self.client.download_asset.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_cancel_after_download_and_during_verification_cleans_part(self):
        def cancel_download(url, path, event, progress):
            path.write_bytes(ZIP_CONTENT)
            event.set()
        self.client.download_asset.side_effect = cancel_download
        with self.assertRaises(AppUpdateCancelled):
            self.service.download_update(update_result(), self.destination, self.event)
        self.assert_no_parts()
        self.event.clear()
        self.client.download_asset.side_effect = self.write_download
        def cancel_verifying(value):
            if value.stage is UpdateProgressStage.VERIFYING:
                self.event.set()
        with self.assertRaises(AppUpdateCancelled):
            self.service.download_update(update_result(), self.destination, self.event, cancel_verifying)
        self.assertFalse(self.destination.exists())
        self.assert_no_parts()

    def test_stream_cancel_or_failure_preserves_target_and_removes_partial_file(self):
        self.destination.write_bytes(b"old")
        for error in (DownloadCancelled(), GitHubReleaseError("断线"), OSError("disk full")):
            def interrupted(url, path, event, progress):
                path.write_bytes(b"part")
                raise error
            self.client.download_asset.side_effect = interrupted
            with self.subTest(error=error), self.assertRaises(AppUpdateError):
                self.service.download_update(update_result(), self.destination, self.event, overwrite=True)
            self.assertEqual(self.destination.read_bytes(), b"old")
            self.assert_no_parts()

    def test_network_error_after_cancel_is_reported_as_cancelled(self):
        def interrupted(url, path, event, progress):
            path.write_bytes(b"partial")
            event.set()
            raise GitHubReleaseError("读取超时")
        self.client.download_asset.side_effect = interrupted
        with self.assertRaises(AppUpdateCancelled):
            self.service.download_update(update_result(), self.destination, self.event)
        self.assert_no_parts()

    def test_final_rename_failure_does_not_report_success_or_leave_part(self):
        with patch("src.services.app_update_service.os.rename", side_effect=OSError("denied")):
            with self.assertRaisesRegex(AppUpdateError, "无法保存"):
                self.service.download_update(update_result(), self.destination, self.event)
        self.assertFalse(self.destination.exists())
        self.assert_no_parts()

    def test_file_appearing_during_download_is_not_overwritten(self):
        def target_appears(url, path, event, progress):
            path.write_bytes(ZIP_CONTENT)
            self.destination.write_bytes(b"new user file")
        self.client.download_asset.side_effect = target_appears
        with self.assertRaisesRegex(AppUpdateError, "已存在"):
            self.service.download_update(update_result(), self.destination, self.event)
        self.assertEqual(self.destination.read_bytes(), b"new user file")
        self.assert_no_parts()

    def test_invalid_destination_or_missing_directory_prevents_download(self):
        for destination in (self.destination.with_suffix(".exe"), self.destination / "absent.zip"):
            with self.subTest(destination=destination), self.assertRaises(AppUpdateError):
                self.service.download_update(update_result(), destination, self.event)
        self.client.download_asset.assert_not_called()

    def test_invalid_result_or_checksum_prevents_download(self):
        for result in (replace(update_result(), status=UpdateCheckStatus.UP_TO_DATE), replace(update_result(), expected_sha256="bad")):
            with self.assertRaises(AppUpdateError):
                self.service.download_update(result, self.destination, self.event)
        self.client.download_asset.assert_not_called()


if __name__ == "__main__":
    unittest.main()
