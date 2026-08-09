from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
import urllib3
from requests.adapters import HTTPAdapter

from .network_ops import CommandResult, prepare_network_for_sample


VENDOR_PREFIX = "X_SDMC_"
UBUS_SERVICE_BBFDM = "bbfdm"
DEVICE_SAVE_PATH = "/tmp/x_sdmc_firmware.pkgtb"
UPLOAD_PATH = "/cgi-bin/cgi-upload"
UBUS_PATH = "/ubus/"
UPGRADE_STATUS_SUCCESS = 9
UPGRADE_STATUS_FAILURES = {1, 2, 3, 4, 5, 6, 7, 8, 11, 12}
UPGRADE_STATUS_MSG = {
    1: "输入参数错误",
    2: "下载固件错误",
    3: "文件不存在",
    4: "固件验证错误",
    5: "软件版本不匹配",
    6: "硬件版本不匹配",
    7: "CRC校验错误",
    8: "固件写入错误",
    9: "升级成功",
    11: "没有固件",
    12: "签名错误",
}


@dataclass(frozen=True)
class PageUpgradeRequest:
    vlan: str
    bind_ip: str
    device_ip: str
    username: str
    password: str
    firmware_path: Path
    adapter_alias: str = ""
    subnet_mask: str = "255.255.255.0"
    restore_factory: bool = False


@dataclass(frozen=True)
class PageUpgradeItemResult:
    request: PageUpgradeRequest
    result: CommandResult


class SourceAddressAdapter(HTTPAdapter):
    def __init__(self, source_address: tuple[str, int], *args, **kwargs):
        self.source_address = source_address
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["source_address"] = self.source_address
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


class UbusRpcError(RuntimeError):
    def __init__(self, operation: str, response_data: dict):
        self.operation = operation
        self.response_data = response_data
        error = response_data.get("error", {}) if isinstance(response_data, dict) else {}
        self.code = error.get("code")
        self.rpc_message = error.get("message", "")
        super().__init__(f"{operation} 返回错误：{response_data}")

    @property
    def is_access_denied(self) -> bool:
        return self.code == -32002 or str(self.rpc_message).lower() == "access denied"


class UbusUpgradeClient:
    def __init__(self, local_bind_ip: str = "", request_timeout: float = 30.0):
        self.local_bind_ip = local_bind_ip.strip()
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.ubus_url = ""
        self.session_id = ""
        self.username = ""
        self.password = ""
        if self.local_bind_ip:
            adapter = SourceAddressAdapter((self.local_bind_ip, 0))
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def switch_url(self, url: str) -> None:
        self.ubus_url = url

    def login(self, username: str, password: str, attempts: int = 3) -> bool:
        self.username = username
        self.password = password
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": username, "password": password},
            ],
        }
        for _index in range(attempts):
            try:
                response = self.session.post(self.ubus_url, json=payload, timeout=self.request_timeout, verify=False)
                response_data = response.json()
                result = response_data.get("result")
                if not isinstance(result, list) or len(result) < 2 or result[0] != 0:
                    time.sleep(1)
                    continue
                self.session_id = result[1].get("ubus_rpc_session", "")
                if self.session_id:
                    return True
            except Exception:
                time.sleep(1)
        return False

    def call(self, ubus_object: str, ubus_func: str, params: dict | str):
        if not self.session_id:
            raise RuntimeError("未登录或 session 已失效，请先登录 UBUS")
        if isinstance(params, str):
            params = json.loads(params)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [
                self.session_id,
                ubus_object,
                ubus_func,
                params,
            ],
        }
        response = self.session.post(self.ubus_url, json=payload, timeout=self.request_timeout, verify=False)
        try:
            response_data = response.json()
        except Exception as exc:
            raise RuntimeError(f"UBUS 返回无法解析 JSON：{response.text}") from exc
        if "error" in response_data:
            raise UbusRpcError(f"{ubus_object}.{ubus_func}", response_data)
        result = response_data.get("result")
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and "fault" in item:
                    raise RuntimeError(f"UBUS 返回 fault：{item}")
        return result

    def logout(self) -> None:
        if not self.session_id:
            return
        try:
            self.call(
                UBUS_SERVICE_BBFDM,
                "unauthenticated_operate",
                {
                    "command": "Device.X_SDMC_Login.logout()",
                    "input": {"SessionId": self.session_id},
                },
            )
        except Exception:
            pass
        finally:
            self.session_id = ""

    def upload_file(self, local_file_path: Path, device_save_path: str, upload_url: str) -> tuple[int, str]:
        if not local_file_path.is_file():
            raise FileNotFoundError(f"本地文件不存在：{local_file_path}")
        with local_file_path.open("rb") as file:
            response = self.session.post(
                upload_url,
                files={"file": (os.path.basename(device_save_path), file, "application/octet-stream")},
                data={"sessionid": self.session_id, "filename": device_save_path},
                timeout=self.request_timeout,
                verify=False,
            )
        response.raise_for_status()
        return response.status_code, response.text

    def trigger_upgrade(self, on_output: Optional[Callable[[str], None]] = None) -> str:
        command = f"Device.DeviceInfo.{VENDOR_PREFIX}Upgrade()"
        attempts = [
            (
                "bbfdm.operate",
                "operate",
                {"command": command, "input": {"URL": "local"}},
            ),
            (
                "bbfdm.operate(proto=web)",
                "operate",
                {"command": command, "input": {"URL": "local"}, "optional": {"proto": "web"}},
            ),
            (
                "bbfdm.unauthenticated_operate",
                "unauthenticated_operate",
                {"command": command, "input": {"URL": "local", "SessionId": self.session_id}},
            ),
        ]
        last_access_denied: UbusRpcError | None = None
        for label, ubus_func, params in attempts:
            try:
                self.call(UBUS_SERVICE_BBFDM, ubus_func, params)
                return label
            except UbusRpcError as exc:
                if not exc.is_access_denied:
                    raise
                last_access_denied = exc
                if on_output:
                    on_output(f"{label} 触发升级被拒绝，尝试下一种兼容方式。")
        if last_access_denied:
            raise last_access_denied
        raise RuntimeError("触发升级失败：没有可用的 UBUS 调用方式")

    def trigger_factory_reset(self):
        """按公司 SdmcUbusLib 的页面 UBUS 接口下发恢复出厂。"""
        return self.call(
            UBUS_SERVICE_BBFDM,
            "operate",
            {
                "command": "Device.FactoryReset()",
                "optional": {"proto": "web"},
            },
        )

    def query_upgrade_status(self) -> int | None:
        response = self.call(
            UBUS_SERVICE_BBFDM,
            "get",
            {"path": f"Device.DeviceInfo.{VENDOR_PREFIX}GetUpgradeStatus"},
        )
        if not isinstance(response, list) or len(response) < 2:
            raise ValueError("查询返回格式不正确")
        data = response[1] if isinstance(response[1], dict) else {}
        upgrade_info_str = data.get(f"{VENDOR_PREFIX}GetUpgradeStatus", "")
        if not upgrade_info_str:
            raise ValueError("查询返回无升级信息")
        upgrade_info = json.loads(upgrade_info_str)
        status = upgrade_info.get("status")
        return int(status) if status is not None else None


def run_single_page_upgrade(
    request: PageUpgradeRequest,
    on_output: Optional[Callable[[str], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    client_factory: Callable[[str], UbusUpgradeClient] = UbusUpgradeClient,
    status_timeout_seconds: float = 180,
    status_interval_seconds: float = 5,
    reboot_timeout_seconds: float = 360,
    reboot_interval_seconds: float = 30,
) -> CommandResult:
    def emit(message: str) -> None:
        if on_output:
            on_output(message)

    label = request.vlan or request.device_ip
    if not request.firmware_path.is_file():
        return CommandResult(False, f"{label} 页面升级失败：固件文件不存在：{request.firmware_path}")

    if request.adapter_alias:
        network_result = prepare_network_for_sample(
            request.adapter_alias,
            request.bind_ip,
            request.subnet_mask,
            on_output=emit,
            sleep_fn=sleep_fn,
            reuse_if_ready=True,
        )
        if not network_result.ok:
            return CommandResult(False, f"{label} 页面升级失败：{network_result.message}")

    client = client_factory(request.bind_ip)
    try:
        scheme = _login_with_fallback(client, request, emit)
        if not scheme:
            return CommandResult(False, f"{label} 页面升级失败：HTTP/HTTPS 均无法登录 UBUS")

        upload_url = f"{scheme}://{request.device_ip}{UPLOAD_PATH}"
        emit(f"{label} 上传固件到设备：{upload_url}")
        status_code, upload_msg = client.upload_file(request.firmware_path, DEVICE_SAVE_PATH, upload_url)
        if status_code != 200:
            return CommandResult(False, f"{label} 页面升级失败：上传返回 {status_code}，{upload_msg}")

        emit(f"{label} 触发 UBUS 升级命令")
        trigger_method = client.trigger_upgrade(on_output=emit)
        emit(f"{label} 升级命令已触发：{trigger_method}")

        status_result = _wait_for_upgrade_success(
            client,
            label,
            emit,
            sleep_fn=sleep_fn,
            timeout_seconds=status_timeout_seconds,
            interval_seconds=status_interval_seconds,
        )
        if not status_result.ok:
            return status_result

        emit(f"{label} 等待设备重启并重新上线")
        reboot_result = _wait_for_reboot_login(
            client,
            label,
            request.username,
            request.password,
            emit,
            sleep_fn=sleep_fn,
            timeout_seconds=reboot_timeout_seconds,
            interval_seconds=reboot_interval_seconds,
        )
        if not reboot_result.ok:
            return reboot_result
        if request.restore_factory:
            emit(f"{label} 已完成升级并重新登录成功，恢复出厂：开启，开始下发 UBUS 命令")
            client.trigger_factory_reset()
            emit(f"{label} TX UBUS Device.FactoryReset()")
            emit(f"{label} UBUS 恢复出厂命令已下发")
        else:
            emit(f"{label} 已完成升级并重新登录成功，恢复出厂：关闭，跳过")
        return CommandResult(True, f"{label} 页面升级完成。")
    except requests.RequestException as exc:
        return CommandResult(False, f"{label} 页面升级请求异常：{exc}")
    except Exception as exc:
        return CommandResult(False, f"{label} 页面升级异常：{exc}")
    finally:
        client.logout()


def run_page_upgrade_batch(
    requests_: list[PageUpgradeRequest],
    on_output: Optional[Callable[[str], None]] = None,
    on_item_complete: Optional[Callable[[PageUpgradeItemResult], None]] = None,
    max_workers: int = 8,
) -> list[PageUpgradeItemResult]:
    if not requests_:
        return []
    workers = max(1, min(max_workers, len(requests_)))
    results: list[PageUpgradeItemResult] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(run_single_page_upgrade, request, on_output): request
            for request in requests_
        }
        for future in as_completed(future_map):
            request = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = CommandResult(False, f"{request.vlan or request.device_ip} 页面升级异常：{exc}")
            item_result = PageUpgradeItemResult(request=request, result=result)
            results.append(item_result)
            if on_item_complete:
                on_item_complete(item_result)
    return sorted(results, key=lambda item: requests_.index(item.request))


def _login_with_fallback(
    client: UbusUpgradeClient,
    request: PageUpgradeRequest,
    emit: Callable[[str], None],
) -> str:
    label = request.vlan or request.device_ip
    for scheme in ("http", "https"):
        client.switch_url(f"{scheme}://{request.device_ip}{UBUS_PATH}")
        emit(f"{label} 尝试使用 {scheme.upper()} 登录 UBUS：{client.ubus_url}")
        if client.login(request.username, request.password):
            emit(f"{label} UBUS 登录成功")
            return scheme
        emit(f"{label} {scheme.upper()} 登录失败，尝试下一种协议")
    return ""


def _wait_for_upgrade_success(
    client: UbusUpgradeClient,
    label: str,
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None],
    timeout_seconds: float,
    interval_seconds: float,
) -> CommandResult:
    deadline = time.monotonic() + timeout_seconds
    last_status = None
    while time.monotonic() < deadline:
        try:
            status = client.query_upgrade_status()
            if status != last_status:
                last_status = status
                status_msg = UPGRADE_STATUS_MSG.get(status, "未知状态码")
                emit(f"{label} 当前升级状态：{status}（{status_msg}）")
            if status == UPGRADE_STATUS_SUCCESS:
                return CommandResult(True, f"{label} 已确认升级状态成功")
            if status in UPGRADE_STATUS_FAILURES:
                return CommandResult(False, f"{label} 页面升级失败：{status}（{UPGRADE_STATUS_MSG.get(status, '未知状态码')}）")
        except Exception as exc:
            emit(f"{label} 查询升级状态异常，继续等待：{exc}")
        sleep_fn(interval_seconds)
    if last_status is None:
        return CommandResult(False, f"{label} 页面升级失败：等待升级状态超时，未获取到状态")
    return CommandResult(False, f"{label} 页面升级失败：等待成功状态超时，最后状态 {last_status}")


def _wait_for_reboot_login(
    client: UbusUpgradeClient,
    label: str,
    username: str,
    password: str,
    emit: Callable[[str], None],
    sleep_fn: Callable[[float], None],
    timeout_seconds: float,
    interval_seconds: float,
) -> CommandResult:
    waited = 0.0
    while waited < timeout_seconds:
        sleep_fn(interval_seconds)
        waited += interval_seconds
        emit(f"{label} 尝试重新登录设备，第 {int(waited // interval_seconds)} 次")
        if client.login(username, password, attempts=1):
            emit(f"{label} 设备已重新上线")
            return CommandResult(True, f"{label} 重启后登录成功")
    return CommandResult(False, f"{label} 页面升级失败：等待设备重启上线超时")
