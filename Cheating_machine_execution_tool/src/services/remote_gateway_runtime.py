"""Explicit opt-in source runtime. Existing direct DingTalk/Feishu startup stays unchanged."""
import base64
import json
import os
from pathlib import Path
import uuid

from src.core.ai_credentials import WindowsCredentialCipher
from src.core.remote_gateway_transport import GatewayInstanceClient
from src.services.ai_project_store import initialize_project, project_directory
from src.services.ai_store import DiagnosticStore
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.remote_instance_service import GatewayAgentBridge
from src.services.host_resource_fence import HostResourceFence


class RemoteInstanceConfig:
    def __init__(self, identity, cipher=None, *, pending=False):
        self.identity, self.cipher = identity, cipher or WindowsCredentialCipher()
        self.path = identity.directory / ("gateway.pending.json" if pending else "gateway.json")
        self.binding = "gateway-instance|" + identity.instance_id + "|" + str(identity.directory.resolve())

    def load(self):
        if not self.path.exists():
            raise ValueError("该实例槽位尚未配对统一网关")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        value["credential"] = self.cipher.decrypt(base64.b64decode(value.pop("encrypted")), self.binding)
        if value["instance_id"] != self.identity.instance_id:
            raise ValueError("配置不属于当前永久实例")
        return value

    def save(self, value):
        value = dict(value)
        if value.get("instance_id") != self.identity.instance_id:
            raise ValueError("配置不属于当前永久实例")
        value["encrypted"] = base64.b64encode(self.cipher.encrypt(value.pop("credential"), self.binding)).decode("ascii")
        temporary = self.path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class RemoteGatewayRuntime:
    def __init__(self, app_dir, slot, *, cipher=None, storage_root=None, fence_directory=None):
        self.identity = RemoteInstanceIdentity(app_dir, slot=slot, storage_root=storage_root)
        self.client = self.bridge = self.fence = None
        self.fence_directory = fence_directory
        try:
            pending = RemoteInstanceConfig(self.identity, cipher, pending=True)
            if pending.path.exists():
                value = pending.load()
                if not value.get("enabled") or not value.get("channel_ids") or not value.get("capability_ids"):
                    raise ValueError("待生效统一接入范围无效，请重新保存")
                RemoteInstanceConfig(self.identity, cipher).save(value)
                pending.path.unlink()
            self.config = RemoteInstanceConfig(self.identity, cipher).load()
            if not self.config.get("enabled"):
                raise ValueError("统一接入尚未在本地确认通道及能力范围，未启用")
        except BaseException:
            self.identity.close()
            raise

    def open_store(self, app_dir, emit):
        from src.services.ai_case_store import open_shared_cases
        legacy = project_directory(app_dir) / "diagnostics.sqlite3"
        initialize_project(self.identity.directory, legacy=legacy if legacy.exists() else None)
        return DiagnosticStore(self.identity.directory, case_store=open_shared_cases(emit))

    def attach(self, conversation, project_path):
        capabilities = getattr(conversation, "capabilities", None)
        if capabilities is None:
            raise ValueError("实例尚未装配Capability Service，统一接入不启动")
        # Shared across slots and program copies on this host; tests inject a temporary root.
        root = self.fence_directory or Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "LineCheckAssistant" / "host-resource-fence"
        self.fence = HostResourceFence(root)
        capabilities.service.resources.fence = self.fence
        self.bridge = GatewayAgentBridge(conversation, self.identity, self.config["scopes"], self.config["channel_ids"],
            self.config["capability_ids"], enabled=True, project_path=project_path)
        self.client = GatewayInstanceClient(self.config["url"], self.config["credential"], self.bridge,
            vpn=self.config.get("vpn", False), emit=conversation.emit).start()
        conversation.emit("[统一接入] 本地范围已启用；实例=" + self.identity.instance_id[:8] +
                          "；启动=" + self.identity.run_id[:8] + "；远程新会话请求批准")

    def begin_close(self):
        if self.client:
            self.client.begin_close()
        if self.bridge:
            self.bridge.set_enabled(False)

    @property
    def idle(self):
        return self.client is None or self.client.idle

    def close(self):
        if self.client:
            self.client.close()
        if self.bridge:
            self.bridge.close()
        if self.fence:
            self.fence.close()
        self.identity.close()
