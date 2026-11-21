"""Local multi-instance control plane; only sanitized status is an AI capability."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import threading
import uuid

from src.core.remote_gateway_transport import GatewayConnection
from src.models.capabilities import CapabilitySpec, object_schema
from src.models.dependency_repair import maintenance_operation
from src.services.ai_project_store import project_directory
from src.services.remote_gateway_host import RemoteGatewayHost
from src.services.remote_gateway_store import validate_pairing_scopes
from src.services.remote_gateway_runtime import RemoteInstanceConfig
from src.services.remote_instance_identity import RemoteInstanceIdentity


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_startup(app_dir):
    path = project_directory(app_dir) / "instance_startup.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(mode="direct", slot=1)
    if not isinstance(value, dict) or value.get("mode") not in ("direct", "gateway") or type(value.get("slot")) is not int or not 1 <= value["slot"] <= 64:
        raise ValueError("多实例启动设置无效，请在多实例管理页重新保存")
    return dict(mode=value["mode"], slot=value["slot"])


def _save_pending_startup(pending, value, startup_path, startup, emit):
    # Keep a byte-exact encrypted copy. Restoring by rename also works when
    # the second file could not be written because the volume was full.
    backup = pending.path.with_suffix("." + uuid.uuid4().hex + ".bak")
    existed = pending.path.exists()
    if existed:
        try:
            shutil.copyfile(pending.path, backup)
        except OSError:
            backup.unlink(missing_ok=True)
            raise
    try:
        pending.save(value)
        atomic_json(startup_path, startup)
    except Exception:
        if existed:
            os.replace(backup, pending.path)
        else:
            pending.path.unlink(missing_ok=True)
        raise
    if existed:
        try:
            backup.unlink()
        except OSError:
            emit("[多实例管理] 启动配置已写入；旧的加密临时备份未能清理：" + backup.name)


def selected_gateway_slot(app_dir, environ=None):
    environment = os.environ if environ is None else environ
    explicit = environment.get("LINECHECK_GATEWAY_SLOT", "")
    if explicit:
        try:
            slot = int(explicit)
        except (TypeError, ValueError):
            raise ValueError("统一接入槽位须为1至64") from None
        if not 1 <= slot <= 64:
            raise ValueError("统一接入槽位须为1至64")
        return slot
    value = read_startup(app_dir)
    return value["slot"] if value["mode"] == "gateway" else None


class RemoteInstanceManagement:
    def __init__(self, app_dir, *, runtime=lambda: None, registry=lambda: None, emit=lambda line: None,
                 cipher=None, host=None, connection_factory=GatewayConnection, maintenance=None):
        self.app_dir, self.runtime, self.registry = Path(app_dir), runtime, registry
        self.emit, self.cipher, self.connection_factory = emit, cipher, connection_factory
        self.host = host or RemoteGatewayHost(emit=emit, cipher=cipher)
        self.maintenance = maintenance
        self.lock = threading.RLock()
        self.closing = False
        self.close_thread = None
        self.close_error = ""

    def _admit(self):
        if self.closing:
            raise ValueError("程序正在退出，多实例管理操作未执行")

    @contextmanager
    def _identity(self, slot):
        current = self.runtime()
        if current is not None and current.identity.slot == slot:
            yield current.identity
        else:
            identity = RemoteInstanceIdentity(self.app_dir, slot=slot)
            try:
                yield identity
            finally:
                identity.close()

    def capabilities(self, registry=None):
        if registry is None:
            registry = self.registry()
        if registry is None:
            return []
        # Only remote-capable business APIs; never control-plane or extension grants.
        return [row for row in registry.list() if registry.get(row["capability_id"]).sources
                and set(registry.get(row["capability_id"]).sources) & {"dingtalk", "feishu"}
                and not row["capability_id"].startswith(("extension.", "remote."))]

    def slot(self, number):
        with self.lock, self._identity(number) as identity:
            config = RemoteInstanceConfig(identity, self.cipher)
            pending = RemoteInstanceConfig(identity, self.cipher, pending=True)
            path = pending if pending.path.exists() else config
            value = path.load() if path.path.exists() else {}
            return dict(slot=number, instance_id=identity.instance_id, paired=bool(value),
                        pending=pending.path.exists(), url=value.get("url", ""), name=value.get("name", ""),
                        vpn=value.get("vpn", False), scopes=value.get("scopes", []),
                        channel_ids=value.get("channel_ids", []), capability_ids=value.get("capability_ids", []),
                        enabled=value.get("enabled", False))

    @maintenance_operation
    def pair(self, number, url, name, vpn, code):
        with self.lock:
            self._admit()
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 160:
                raise ValueError("请填写1至160字的实例名称")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("请填写一次性配对码")
            with self._identity(number) as identity:
                config = RemoteInstanceConfig(identity, self.cipher)
                if config.path.exists() or RemoteInstanceConfig(identity, self.cipher, pending=True).path.exists():
                    raise ValueError("该槽位已有配对身份；首批重配请使用新的空闲槽位，保留原任务记录")
                self.emit("[多实例管理] 开始配对；槽位=" + str(number))
                connection = self.connection_factory(url, vpn=vpn)
                try:
                    pairing = connection.pair(code.strip(), identity.instance_id, name.strip())
                except Exception:
                    self.emit("[多实例管理] 配对失败或结果未确认；未自动重试，请核对网关登记及配对码")
                    raise ValueError("配对失败或结果未确认，请核对地址、VPN/WSS、配对码及网关登记") from None
                finally:
                    connection.close()
                config.save(dict(pairing, url=url, name=name.strip(), vpn=vpn, enabled=False,
                                 channel_ids=[], capability_ids=[]))
                self.emit("[多实例管理] 配对成功；实例=" + identity.instance_id + "；等待本地确认范围")
            return self.slot(number)

    @maintenance_operation
    def save_instance(self, mode, number, url, vpn, channels, capabilities, *, registry=None):
        with self.lock:
            self._admit()
            if mode not in ("direct", "gateway") or type(number) is not int or not 1 <= number <= 64:
                raise ValueError("请选择接入模式和1至64的槽位")
            startup_path = project_directory(self.app_dir) / "instance_startup.json"
            startup = dict(mode=mode, slot=number)
            if mode == "gateway":
                if not channels or any(type(n) is not int or not 1 <= n <= 16 for n in channels):
                    raise ValueError("请明确选择允许通道1至16")
                allowed = {v["capability_id"] for v in self.capabilities(registry)}
                if not capabilities or set(capabilities) - allowed:
                    raise ValueError("请从当前已注册且支持远程的能力中选择允许范围")
                GatewayConnection(url, vpn=vpn)  # Validate endpoint, without opening a connection.
                with self._identity(number) as identity:
                    original = RemoteInstanceConfig(identity, self.cipher)
                    pending = RemoteInstanceConfig(identity, self.cipher, pending=True)
                    value = (pending if pending.path.exists() else original).load()
                    value.update(url=url, vpn=bool(vpn), enabled=True,
                                 channel_ids=sorted(set(channels)), capability_ids=sorted(set(capabilities)))
                    _save_pending_startup(pending, value, startup_path, startup, self.emit)
            else:
                atomic_json(startup_path, startup)
            self.emit("[多实例管理] 启动配置已保存；模式=" + mode + "；槽位=" + str(number) +
                      "；通道=" + ",".join(map(str, channels)) + "；能力=" + ",".join(capabilities) + "；下次启动生效")

    def gateway_config(self):
        path = self.host.directory / "gui_config.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(
            host="127.0.0.1", port=18761, vpn=False, certificate="", private_key="", platforms=[], scopes=[])

    @maintenance_operation
    def save_gateway(self, config, scopes):
        with self.lock:
            self._admit()
            value = self.host.validate(config)
            if scopes:
                validate_pairing_scopes(scopes)
            atomic_json(self.host.directory / "gui_config.json", dict(value, scopes=scopes))
            self.emit("[多实例管理] 网关配置已保存；监听=" + value["host"] + ":" + str(value["port"]) +
                      "；平台=" + ",".join(value["platforms"]) + "；重新启动网关后生效")

    def platform_configs(self, platforms):
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from src.services.feishu_remote_store import FeishuConfigStore
        result = {}
        for platform in platforms:
            value = (RemoteConfigStore if platform == "dingtalk" else FeishuConfigStore)(self.app_dir).load()
            if not value.get("corp") or not value.get("group"):
                raise ValueError("请先在远程管理完成所选机器人的配置和群绑定")
            if value.get("enabled"):
                raise ValueError("所选机器人直接接入已启用，请先在远程管理关闭对应接入")
            result[platform] = dict(value, enabled=True)
            if platform == "feishu":
                result[platform]["group_enabled"] = True
        return result

    def bound_scope(self, platform):
        from src.services.dingtalk_remote_store import RemoteConfigStore
        from src.services.feishu_remote_store import FeishuConfigStore
        config = (RemoteConfigStore if platform == "dingtalk" else FeishuConfigStore)(self.app_dir).load()
        return dict(platform=platform, robot=config.get("robot_code" if platform == "dingtalk" else "app_id", ""),
                    corp=config.get("corp", ""), chat_type="group", chat=config.get("group", ""), members=[])

    @maintenance_operation
    def start_gateway(self):
        with self.lock:
            self._admit()
            if getattr(self.runtime(), 'mode', '') == 'project_peers':
                raise ValueError('项目路由模式已启用，请退出该模式后启动旧网关')
            value = self.gateway_config()
            self.emit("[多实例管理] 开始启动网关；监听=" + value["host"] + ":" + str(value["port"]))
            self.host.start(value, self.platform_configs(value["platforms"]))

    def stop_gateway(self):
        with self.lock:
            self._admit()
            if self.host.state() == "外部运行":
                raise ValueError("网关由外部进程运行，请回原启动入口停止")
            self.host.stop()
            self.emit("[多实例管理] 网关已停止；远端已准入业务继续执行")

    @maintenance_operation
    def create_pairing(self):
        with self.lock:
            self._admit()
            scopes = self.gateway_config().get("scopes", [])
            code = self.host.create_pairing(scopes)
            self.emit("[多实例管理] 已生成一次性配对码；5分钟有效；范围条数=" + str(len(scopes)))
            return code

    @maintenance_operation
    def revoke(self, instance_id):
        with self.lock:
            self._admit()
            self.host.revoke(instance_id)

    def status(self):
        current = self.runtime()
        mode = getattr(current, 'mode', 'gateway') if current is not None else 'direct'
        if getattr(self, 'startup_error', False):
            mode = 'error'
        return dict(current_mode=mode, gateway_state=self.host.state(),
                    current_slot=current.identity.slot if current else None,
                    instance_id=current.identity.instance_id if current else "",
                    run_id=current.identity.run_id if current else "",
                    connected=bool(current and current.client and current.client.connected.is_set()))

    def register_status(self, registry):
        registry.register(CapabilitySpec("remote.instances.status", "查询本机多实例接入状态",
            "只读查询本机当前模式、槽位和网关状态；不返回凭据、配对码或其它成员范围，不允许配置或授权。",
            object_schema(), lambda a, auth: self.status(), sources=("local", "gui")))

    def begin_close(self):
        self.closing = True
        if self.close_thread is None:
            def close():
                with self.lock:
                    try:
                        self.host.stop()
                    except Exception:
                        self.close_error = "网关仍在收尾，等待再次停止"
                        self.emit("[多实例管理] " + self.close_error)
            self.close_thread = threading.Thread(target=close, name="multi-instance-close", daemon=True)
            self.close_thread.start()

    @property
    def idle(self):
        if self.close_thread and self.close_thread.is_alive():
            return False
        if self.close_error:
            self.close_error = ""
            self.close_thread = None
            self.begin_close()
            return False
        return True
