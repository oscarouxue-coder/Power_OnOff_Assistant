from __future__ import annotations

import threading
import time
from typing import Callable, Iterable, Optional, Type

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.core.zte_olt_telnet import (
    CLI_ERROR_RE,
    OltCommandError,
    OperationCancelled,
    ZteOltTelnetSession,
)
from src.models.onu_registration_models import (
    C300CleanupCandidate,
    OLT_FAMILY_C300,
    OLT_FAMILY_C600,
    OltConnection,
    OnuDiscoveryScope,
    OnuOperationResult,
    OnuProvisionRequest,
)


DRIVER_TYPES = {
    OLT_FAMILY_C300: ZteC300OnuDriver,
    OLT_FAMILY_C600: ZteC600OnuDriver,
}


def driver_for_family(family: str):
    try:
        return DRIVER_TYPES[family]()
    except KeyError as exc:
        raise ValueError(f"不支持的 OLT 型号：{family}") from exc


class OnuRegistrationService:
    def __init__(
        self,
        logger: Optional[Callable[[str], None]] = None,
        session_type: Type[ZteOltTelnetSession] = ZteOltTelnetSession,
        readiness_timeout: float = 60.0,
        readiness_interval: float = 3.0,
    ) -> None:
        self.logger = logger or (lambda _message: None)
        self.session_type = session_type
        self.readiness_timeout = max(0.0, readiness_timeout)
        self.readiness_interval = max(0.1, readiness_interval)

    def _log(self, family: str, message: str) -> None:
        self.logger(f"[ONU注册][{family}] {message}")

    def test_connection(
        self,
        family: str,
        connection: OltConnection,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        try:
            driver_for_family(family)
            self._log(family, "开始 OLT 登录测试")
            with self.session_type(connection, logger=lambda text: self._log(family, text), cancel_event=cancel_event):
                pass
            self._log(family, "OLT 登录测试成功")
            return OnuOperationResult(True, "OLT Telnet 登录成功")
        except OperationCancelled as exc:
            self._log(family, str(exc))
            return OnuOperationResult(False, str(exc))
        except Exception as exc:
            self._log(family, f"OLT 登录测试失败：{exc}")
            return OnuOperationResult(False, f"OLT 登录失败：{exc}")

    def query_unregistered(
        self,
        family: str,
        connection: OltConnection,
        scope: Optional[OnuDiscoveryScope] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        driver = driver_for_family(family)
        query_scope = scope or OnuDiscoveryScope()
        try:
            command = driver.build_discovery_command(query_scope)
            self._log(family, "开始查询未注册 ONU")
            with self.session_type(
                connection,
                logger=lambda text: self._log(family, text),
                cancel_event=cancel_event,
            ) as session:
                if family == OLT_FAMILY_C300:
                    session.execute("terminal length 0")
                output = session.execute(command, timeout=30)
            onus = tuple(driver.parse_discovery(output))
            message = f"查询到 {len(onus)} 个未注册 ONU" if onus else "未查询到未注册 ONU"
            self._log(family, message)
            return OnuOperationResult(True, message, output=output, onus=onus, commands=(command,))
        except OperationCancelled as exc:
            self._log(family, str(exc))
            return OnuOperationResult(False, str(exc))
        except Exception as exc:
            self._log(family, f"查询失败：{exc}")
            return OnuOperationResult(False, f"查询未注册 ONU 失败：{exc}")

    def build_preview(self, requests: Iterable[OnuProvisionRequest]) -> tuple[str, ...]:
        preview: list[str] = []
        for request in requests:
            driver = driver_for_family(request.family)
            errors = driver.validate_request(request)
            if errors:
                raise ValueError("；".join(errors))
            preview.extend(driver.build_provision_commands(request))
        return tuple(preview)

    def query_c300_cleanup_candidates(
        self,
        connection: OltConnection,
        request: OnuProvisionRequest,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        driver = ZteC300OnuDriver()
        errors = driver.validate_request(request)
        if errors:
            return OnuOperationResult(False, "；".join(errors))
        commands = ["terminal length 0", "show gpon onu state"]
        outputs: list[str] = []
        try:
            self._log(OLT_FAMILY_C300, "查询目标 PON 的离线 ONU 清理候选")
            with self.session_type(
                connection,
                logger=lambda text: self._log(OLT_FAMILY_C300, text),
                cancel_event=cancel_event,
            ) as session:
                outputs = session.execute_many(commands, timeout=30)
                candidates = driver.cleanup_candidates(request, outputs[1])
                enriched = []
                for candidate in candidates:
                    command = (
                        f"show gpon onu baseinfo {candidate.pon_interface} {candidate.onu_id}"
                    )
                    output = session.execute(command, timeout=20, fail_on_cli_error=False)
                    commands.append(command)
                    outputs.append(output)
                    enriched.append(driver.with_cleanup_identity(candidate, output))
            message = (
                f"查询到 {len(enriched)} 个同 PON 离线候选，请明确选择一台"
                if enriched
                else "目标 PON 未查询到可选的离线 ONU；不会执行删除"
            )
            self._log(OLT_FAMILY_C300, message)
            return OnuOperationResult(
                True,
                message,
                output="\n\n".join(outputs),
                cleanup_candidates=tuple(enriched),
                commands=tuple(commands),
            )
        except OperationCancelled as exc:
            return OnuOperationResult(False, str(exc), output="\n\n".join(outputs), commands=tuple(commands))
        except Exception as exc:
            self._log(OLT_FAMILY_C300, f"离线候选查询失败：{exc}")
            return OnuOperationResult(
                False,
                f"C300 离线候选查询失败：{exc}",
                output="\n\n".join(outputs),
                commands=tuple(commands),
            )

    @staticmethod
    def _execute_precheck(session, driver, commands: Iterable[str]) -> list[str]:
        outputs: list[str] = []
        allow_error = getattr(driver, "precheck_allows_cli_error", lambda _command: False)
        for command in commands:
            outputs.append(
                session.execute(
                    command,
                    timeout=30,
                    fail_on_cli_error=not allow_error(command),
                )
            )
        return outputs

    def _wait_until_ready(
        self,
        family: str,
        driver,
        request: OnuProvisionRequest,
        session,
        cancel_event: threading.Event,
    ) -> tuple[list[str], list[str]]:
        command = driver.build_readiness_command(request)
        commands: list[str] = []
        outputs: list[str] = []
        deadline = time.monotonic() + self.readiness_timeout
        attempt = 0
        last_state = "未查询"
        while True:
            attempt += 1
            output = session.execute(command, timeout=30, fail_on_cli_error=False)
            if CLI_ERROR_RE.search(output) and not any(
                marker in output.lower()
                for marker in ("onu data is null", "no related information to show")
            ):
                raise OltCommandError(command, output)
            commands.append(command)
            outputs.append(output)
            ready, last_state = driver.readiness_state(request, output)
            self._log(family, f"ONU 上线检查第 {attempt} 次：{last_state}")
            if ready:
                return commands, outputs
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"配置已下发，但 ONU 未在 {self.readiness_timeout:.0f} 秒内上线：{last_state}"
                )
            if cancel_event.wait(min(self.readiness_interval, remaining)):
                raise OperationCancelled("操作已停止")

    def register(
        self,
        connection: OltConnection,
        requests: Iterable[OnuProvisionRequest],
        c300_cleanup_candidate: Optional[C300CleanupCandidate] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        items = tuple(requests)
        if not items:
            return OnuOperationResult(False, "未选择要注册的 ONU")
        families = {item.family for item in items}
        if len(families) != 1:
            return OnuOperationResult(False, "一次操作不能混合 C300 和 C600 ONU")
        family = next(iter(families))
        if len(items) != 1:
            return OnuOperationResult(False, f"{family} 每次只能注册一台 ONU")
        driver = driver_for_family(family)
        all_commands: list[str] = []
        all_outputs: list[str] = []
        session = self.session_type(
            connection,
            logger=lambda text: self._log(family, text),
            cancel_event=cancel_event,
        )
        try:
            for request in items:
                errors = driver.validate_request(request)
                if errors:
                    raise ValueError("；".join(errors))
            session.connect()
            for index, request in enumerate(items, 1):
                target = request.onu.onu_interface or request.onu.pon_interface
                self._log(family, f"阶段 1/3：下发前检查 {index}/{len(items)} {target}")
                precheck_commands = driver.build_precheck_commands(request)
                precheck_outputs = self._execute_precheck(session, driver, precheck_commands)
                all_commands.extend(precheck_commands)
                all_outputs.extend(precheck_outputs)
                precheck_errors = driver.validate_precheck(request, precheck_outputs)
                if precheck_errors:
                    raise RuntimeError("；".join(precheck_errors))

                provision_commands = driver.build_provision_commands(request)
                self._log(family, f"阶段 2/3：注册与业务配置 {index}/{len(items)} {target}")
                try:
                    provision_outputs = session.execute_many(provision_commands, timeout=25)
                except OltCommandError:
                    if family != OLT_FAMILY_C300 or c300_cleanup_candidate is None:
                        raise
                    self._log(
                        family,
                        "C300 配置失败，已授权重新确认并只删除指定离线 ONU："
                        f"{c300_cleanup_candidate.onu_interface}",
                    )
                    session.best_effort_end()
                    session.execute("terminal length 0")
                    state_output = session.execute("show gpon onu state", timeout=30)
                    identity_command = (
                        f"show gpon onu baseinfo {c300_cleanup_candidate.pon_interface} "
                        f"{c300_cleanup_candidate.onu_id}"
                    )
                    identity_output = session.execute(
                        identity_command,
                        timeout=20,
                        fail_on_cli_error=False,
                    )
                    all_commands.extend(
                        ["terminal length 0", "show gpon onu state", identity_command]
                    )
                    all_outputs.extend([state_output, identity_output])
                    identities = driver.parse_baseinfo(identity_output)
                    current_identity = identities[0] if identities else None
                    if (
                        not c300_cleanup_candidate.serial_number
                        or current_identity is None
                        or current_identity["interface"].lower()
                        != c300_cleanup_candidate.onu_interface.lower()
                        or current_identity["serial_number"].upper()
                        != c300_cleanup_candidate.serial_number.upper()
                    ):
                        raise RuntimeError(
                            "指定 C300 离线 ONU 的 SN 已变化或无法确认，拒绝删除和重试"
                        )
                    cleanup_commands = driver.build_cleanup_commands(
                        request,
                        state_output,
                        c300_cleanup_candidate.onu_interface,
                    )
                    if not cleanup_commands:
                        raise RuntimeError(
                            "指定 C300 ONU 已不在目标 PON 离线候选中，拒绝删除和重试"
                        )
                    cleanup_outputs = session.execute_many(cleanup_commands, timeout=25)
                    all_commands.extend(cleanup_commands)
                    all_outputs.extend(cleanup_outputs)
                    self._log(family, "C300 离线 ONU 删除完成，重新执行原注册命令")
                    provision_outputs = session.execute_many(provision_commands, timeout=25)
                all_commands.extend(provision_commands)
                all_outputs.extend(provision_outputs)

                self._log(family, f"阶段 3/3：等待 ONU 上线并执行只读验证 {index}/{len(items)} {target}")
                readiness_commands, readiness_outputs = self._wait_until_ready(
                    family,
                    driver,
                    request,
                    session,
                    cancel_event or threading.Event(),
                )
                all_commands.extend(readiness_commands)
                all_outputs.extend(readiness_outputs)
                verify_commands = driver.build_verify_commands(request)
                verify_outputs = session.execute_many(verify_commands, timeout=35)
                all_commands.extend(verify_commands)
                all_outputs.extend(verify_outputs)
                verify_errors = driver.validate_verification(request, verify_outputs)
                if verify_errors:
                    raise RuntimeError("；".join(verify_errors))
                self._log(family, f"ONU 注册与验证成功：{target}")
            message = f"已完成 {len(items)} 个 {family} ONU 注册配置和只读验证（未执行 write）"
            return OnuOperationResult(
                True,
                message,
                output="\n\n".join(all_outputs),
                commands=tuple(all_commands),
            )
        except OperationCancelled as exc:
            session.best_effort_end()
            self._log(family, str(exc))
            return OnuOperationResult(False, str(exc), output="\n\n".join(all_outputs), commands=tuple(all_commands))
        except Exception as exc:
            session.best_effort_end()
            self._log(family, f"注册失败：{exc}")
            return OnuOperationResult(
                False,
                f"ONU 注册失败：{exc}",
                output="\n\n".join(all_outputs),
                commands=tuple(all_commands),
            )
        finally:
            session.close()

    def save_configuration(
        self,
        family: str,
        connection: OltConnection,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        driver = driver_for_family(family)
        if not driver.supports_write:
            return OnuOperationResult(False, f"{family} 路径不提供自动 write，请由操作员现场决定")
        try:
            self._log(family, "开始执行独立 write 保存")
            with self.session_type(
                connection,
                logger=lambda text: self._log(family, text),
                cancel_event=cancel_event,
            ) as session:
                session.execute("end", timeout=5, fail_on_cli_error=False)
                output = session.execute("write", timeout=30)
            self._log(family, "OLT 最新配置已写入启动配置")
            return OnuOperationResult(True, "OLT 最新配置已写入启动配置", output=output, commands=("end", "write"))
        except OperationCancelled as exc:
            self._log(family, str(exc))
            return OnuOperationResult(False, str(exc))
        except Exception as exc:
            self._log(family, f"保存失败：{exc}")
            return OnuOperationResult(False, f"OLT 配置保存失败：{exc}")
