from __future__ import annotations

import threading
from typing import Callable, Iterable, Optional, Type

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.core.zte_olt_telnet import (
    OltCommandError,
    OperationCancelled,
    ZteOltTelnetSession,
)
from src.models.onu_registration_models import (
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
    ) -> None:
        self.logger = logger or (lambda _message: None)
        self.session_type = session_type

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

    def register(
        self,
        connection: OltConnection,
        requests: Iterable[OnuProvisionRequest],
        allow_c300_offline_cleanup: bool = False,
        cancel_event: Optional[threading.Event] = None,
    ) -> OnuOperationResult:
        items = tuple(requests)
        if not items:
            return OnuOperationResult(False, "未选择要注册的 ONU")
        families = {item.family for item in items}
        if len(families) != 1:
            return OnuOperationResult(False, "一次操作不能混合 C300 和 C600 ONU")
        family = next(iter(families))
        if family == OLT_FAMILY_C600 and len(items) != 1:
            return OnuOperationResult(False, "C600 每次只能配置一个 ONU ID")
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
                precheck_outputs = session.execute_many(precheck_commands, timeout=30)
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
                    if family != OLT_FAMILY_C300 or not allow_c300_offline_cleanup:
                        raise
                    self._log(family, "C300 配置失败，已授权查询并删除离线 ONU 后重试")
                    session.best_effort_end()
                    session.execute("terminal length 0")
                    state_output = session.execute("show gpon onu state", timeout=30)
                    cleanup_commands = driver.build_cleanup_commands(request, state_output)
                    if not cleanup_commands:
                        raise RuntimeError("未找到可删除的 C300 离线 ONU，无法重试")
                    cleanup_outputs = session.execute_many(cleanup_commands, timeout=25)
                    all_commands.extend(["terminal length 0", "show gpon onu state", *cleanup_commands])
                    all_outputs.extend([state_output, *cleanup_outputs])
                    self._log(family, "C300 离线 ONU 删除完成，重新执行原注册命令")
                    provision_outputs = session.execute_many(provision_commands, timeout=25)
                all_commands.extend(provision_commands)
                all_outputs.extend(provision_outputs)

                self._log(family, f"阶段 3/3：下发后只读验证 {index}/{len(items)} {target}")
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

