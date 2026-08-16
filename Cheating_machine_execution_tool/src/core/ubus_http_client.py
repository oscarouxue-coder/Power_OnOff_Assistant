"""轻量级 UBUS HTTP 客户端（不复用 SdmcUbusLib）。

背景：
- SdmcUbusLib 是 Robot Framework 测试库:`SdmcUbusLibBase.Url/Username/Password/ubus_rpc_session`
  全为类级 static 字段,多线程会互相覆盖 session；依赖 pycurl/SdmcLog/sdmcstart/SdmcNetworkLib
  等不在 requirements.txt 中的包。
- 本地复刻 ubus_enable_telnet 需要的子集:`login` + `bbfdm.get` + `bbfdm.set` + `bbfdm.add`。
- 多张同网段网卡场景:通过 `source_address=(bind_ip, 0)` 锁定 PC 出口,适配 VLAN 网卡。

协议:
- HTTP POST `{device_host}:{ubus_port}/ubus/`, body = JSON-RPC 2.0 `{"jsonrpc":"2.0","id":..., "method":"call", "params":[session_id, service, method, payload]}`.
- `bbfdm` 在样机上对应 UBUS service 名 `"bbf.shell"`(`UBUS_SERVICE_BBFDM`)。
- login 返回的 result[1].ubus_rpc_session 作为后续 RPC 的 session_id。

只支持本次需要的 service 集——更多 keyword 切片时可逐项扩展。
"""
from __future__ import annotations

import http.client
import json
import socket
from typing import Any, Iterable, Mapping

from .bind_socket import ip_is_bindable_locally


DEFAULT_UBUS_PORT = 80
UBUS_PATH = "/ubus/"
UBUS_SERVICE_BBFDM = "bbf.shell"
JSON_RPC_VERSION = "2.0"


class UbusError(RuntimeError):
    """UBUS HTTP 请求错误（含 JSON-RPC 错误码、HTTP 错误等）。"""


class UbusTransportError(UbusError):
    """UBUS HTTP 连接层瞬时错误；只允许幂等读取按策略重试。"""


class UbusHttpClient:
    """按 VLAN 网卡 IP 锁定源 IP,目标 device_host:port 的 UBUS HTTP 客户端。

    单实例对应一台样机；多台样机并发请为每台创建独立 client 实例（这正是要
    抛弃 SdmcUbusLibBase 类级 static 字段的原因）。

    使用样例:
        client = UbusHttpClient(bind_ip="192.168.29.115",
                                device_host="192.168.29.1",
                                ubus_port=80)
        session_id = client.login("telecomadmin", "nE7jA%5m")
        result = client.bbfdm_get(session_id, "Device.Firewall.X_SDMC_Security.AccessCtrl.Rule.")
        client.close()
    """

    def __init__(
        self,
        bind_ip: str,
        device_host: str,
        ubus_port: int = DEFAULT_UBUS_PORT,
        timeout: float = 8.0,
    ) -> None:
        if not ip_is_bindable_locally(bind_ip):
            raise UbusError(
                f"UBUS 源 IP 不属于本机网卡：{bind_ip}。"
                "请在 network_card_ip.ini 调整对应 VLAN 的 network_card_ip，"
                "或用 'netsh interface ip set address' 重新启用该网卡。"
            )
        self.bind_ip = bind_ip
        self.device_host = device_host
        self.ubus_port = int(ubus_port)
        self.timeout = float(timeout)
        self._connection: http.client.HTTPConnection | None = None
        self._session_id = ""

    def _ensure_connection(self) -> http.client.HTTPConnection:
        if self._connection is not None:
            return self._connection
        # http.client.HTTPConnection(host, port, timeout, source_address)
        # Windows 上 source_address=(bind_ip, 0) 等价于 bind to bind_ip ephemeral port;
        # 本机网卡不可 bind 时预检抛 UbusError。
        self._connection = http.client.HTTPConnection(
            self.device_host,
            self.ubus_port,
            timeout=self.timeout,
            source_address=(self.bind_ip, 0),
        )
        return self._connection

    def _discard_connection(self) -> None:
        """丢弃已异常或已用完的 HTTP 连接，同时保留设备 session。"""

        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def _post(self, params: list) -> Any:
        payload = {
            "jsonrpc": JSON_RPC_VERSION,
            "id": 1,
            "method": "call",
            "params": params,
        }
        body = json.dumps(payload).encode("utf-8")
        try:
            connection = self._ensure_connection()
            connection.request("POST", UBUS_PATH, body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            response_body = response.read()
        except (socket.error, OSError, http.client.HTTPException) as exc:
            # 超时/断连后的 HTTPConnection 不可继续安全复用。先丢弃，让上层仅对
            # bbfdm.get 之类幂等读取决定是否新建连接重试；set/operate 不重发。
            self._discard_connection()
            # 2026-07-18: bind_ip 与 device_host 相同 → PC 把自己作为目标连接,
            # 给操作员明确修复指引(与 TelnetSession._open_socket 同款 hint)。
            hint = ""
            if self.bind_ip == self.device_host:
                hint = (
                    "（提示：bind_ip 与 device_host 相同,PC 无法把自己作为目标连接；"
                    "请检查 network_card_ip.ini 中该 VLAN 的 device_manage_ip 是否误填为 PC 静态 IP,"
                    "样机管理 IP 应是设备自身 IP,典型 192.168.1.1。）"
                )
            raise UbusTransportError(
                f"UBUS HTTP 请求失败 {self.device_host}:{self.ubus_port}：{exc}{hint}"
            ) from exc
        if response.status != 200:
            raise UbusError(
                f"UBUS HTTP 状态非 200：{self.device_host}:{self.ubus_port} status={response.status}"
            )
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UbusError(f"UBUS HTTP 响应非合法 JSON：{self.device_host}:{self.ubus_port}（{exc}）") from exc
        if "error" in decoded:
            raise UbusError(f"UBUS JSON-RPC error：{decoded['error']}")
        return decoded.get("result")

    def login(self, username: str, password: str) -> str:
        """登录样机的 web 管理,返回 ubus_rpc_session。"""
        result = self._post([
            "00000000000000000000000000000000",
            "session",
            "login",
            {"username": str(username), "password": str(password)},
        ])
        # 协议格式: result = [error_code:int, {"ubus_rpc_session": str}]
        if not isinstance(result, list) or len(result) < 2:
            raise UbusError(f"UBUS login 返回格式异常：{result}")
        error_code, session_payload = result[0], result[1]
        if error_code != 0:
            raise UbusError(f"UBUS login 错误：error_code={error_code}, payload={session_payload}")
        session_id = session_payload.get("ubus_rpc_session") if isinstance(session_payload, dict) else None
        if not session_id:
            raise UbusError(f"UBUS login 未返回 ubus_rpc_session：{session_payload}")
        self._session_id = session_id
        return session_id

    def logout(self, session_id: str | None = None) -> Any:
        """释放设备端 Web UBUS 会话；成功或失败后都清除本地会话引用。"""

        active_session = str(session_id or self._session_id or "").strip()
        if not active_session:
            return None
        try:
            return self.bbfdm_unauthenticated_operate(
                active_session,
                "Device.X_SDMC_Login.logout()",
                input_payload={"SessionId": active_session},
            )
        finally:
            if self._session_id == active_session:
                self._session_id = ""

    def call(self, session_id: str, service: str, method: str, payload: Mapping[str, Any]) -> Any:
        return self._post([session_id, service, method, dict(payload)])

    # ---- bbfdm 便捷封装 ----

    def bbfdm_get(
        self,
        session_id: str,
        path: str,
        optional: Mapping[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"path": path}
        if optional is not None:
            payload["optional"] = dict(optional)
        return self.call(session_id, UBUS_SERVICE_BBFDM, "get", payload)

    def bbfdm_set(
        self,
        session_id: str,
        path: str,
        obj_path: Mapping[str, Any],
        optional: Mapping[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"path": path, "obj_path": dict(obj_path)}
        if optional is not None:
            payload["optional"] = dict(optional)
        return self.call(session_id, UBUS_SERVICE_BBFDM, "set", payload)

    def bbfdm_operate(
        self,
        session_id: str,
        command: str,
        input_payload: Mapping[str, Any],
        optional: Mapping[str, Any] | None = None,
    ) -> Any:
        """执行需要登录态的 BBFDM ``operate`` 命令。"""
        payload: dict[str, Any] = {
            "command": command,
            "input": dict(input_payload),
        }
        if optional is not None:
            payload["optional"] = dict(optional)
        return self.call(session_id, UBUS_SERVICE_BBFDM, "operate", payload)

    def bbfdm_add(
        self,
        session_id: str,
        path: str,
        obj_path: Mapping[str, Any],
        optional: Mapping[str, Any] | None = None,
    ) -> Any:
        payload: dict[str, Any] = {"path": path, "obj_path": dict(obj_path)}
        if optional is not None:
            payload["optional"] = dict(optional)
        return self.call(session_id, UBUS_SERVICE_BBFDM, "add", payload)

    def bbfdm_unauthenticated_operate(
        self,
        session_id: str,
        command: str,
        command_key: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
        optional: Mapping[str, Any] | None = None,
    ) -> Any:
        """一次性的 bbf.shell unauthenticated_operate 调用（用于兼容 page_upgrade 的 Protocol）。"""
        payload: dict[str, Any] = {"command": command}
        if command_key is not None:
            payload["command_key"] = command_key
        if input_payload is not None:
            payload["input"] = dict(input_payload)
        if optional is not None:
            payload["optional"] = dict(optional)
        return self.call(session_id, UBUS_SERVICE_BBFDM, "unauthenticated_operate", payload)

    def close(self) -> None:
        if self._session_id:
            try:
                self.logout()
            except Exception:
                # close 是 finally 清理入口；设备会话已失效或网络中断时仍须关闭本机连接。
                self._session_id = ""
        self._discard_connection()
