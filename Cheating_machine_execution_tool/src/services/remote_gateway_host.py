"""Locally owned gateway lifecycle, shared by the GUI and source CLI."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import ssl
import threading
import time

from src.core.host_resource_lock import HostResourceBusy, HostResourceLock
from src.core.remote_gateway_transport import GatewayWebSocketServer, require_protected_endpoint
from src.services.remote_gateway_store import RemoteGatewayStore


def _platform_key(platform, config):
    return platform, config.get("client_id" if platform == "dingtalk" else "app_id", "")


def default_gateway_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LineCheckAssistant" / "gateway"


class RemoteGatewayHost:
    def __init__(self, directory=None, *, emit=lambda line: None, cipher=None,
                 server_factory=GatewayWebSocketServer, platforms_factory=None):
        self.directory = Path(directory) if directory is not None else default_gateway_directory()
        self.emit, self.cipher = emit, cipher
        self.server_factory, self.platforms_factory = server_factory, platforms_factory
        self.lock = threading.RLock()
        self.server = self.platforms = self.store = self.lease = None
        self.running_config = None
        self.stopping = False
        self.platform_keys = set()

    def ensure_direct_available(self, platform, config):
        if _platform_key(platform, config) in self.platform_keys:
            raise ValueError("所选机器人正在用于统一网关，请先停止网关再启用直接接入")

    @staticmethod
    def validate(config):
        value = dict(config)
        host = str(value.get("host", "127.0.0.1")).strip()
        port = value.get("port", 18761)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("网关端口须为1至65535")
        vpn = value.get("vpn", False)
        if type(vpn) is not bool:
            raise ValueError("请明确确认VPN网络")
        certificate, private_key = (str(value.get(k, "")).strip() for k in ("certificate", "private_key"))
        if bool(certificate) != bool(private_key):
            raise ValueError("WSS证书和私钥必须同时选择")
        require_protected_endpoint(host, bool(certificate), vpn)
        platforms = value.get("platforms", [])
        if not isinstance(platforms, list) or any(p not in ("dingtalk", "feishu") for p in platforms):
            raise ValueError("平台只能选择钉钉或飞书")
        return dict(host=host, port=port, vpn=vpn, certificate=certificate, private_key=private_key,
                    platforms=sorted(set(platforms)), platform_config_dir=str(value.get("platform_config_dir", "")))

    def start(self, config, platform_configs=None):
        with self.lock:
            if self.server is not None or self.stopping:
                raise ValueError("网关已经启动或仍在收尾")
            value = self.validate(config)
            configs = platform_configs or {}
            if set(configs) != set(value["platforms"]):
                raise ValueError("请先完成所选机器人配置和群绑定")
            # Claim before opening/recovering the DB: an external CLI retains ownership.
            self.lease = HostResourceLock(["gateway-host:" + str(self.directory.resolve())], reentrant=False).acquire()
            try:
                self.platform_keys = {_platform_key(p, c) for p, c in configs.items()}
                self.store = RemoteGatewayStore(self.directory, cipher=self.cipher)
                context = None
                if value["certificate"]:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(value["certificate"], value["private_key"])
                self.server = self.server_factory(self.store, value["host"], value["port"],
                                                  ssl_context=context, vpn=value["vpn"], emit=self.emit).start()
                if value["platforms"]:
                    from src.services.remote_gateway_platforms import GatewayPlatforms
                    factory = self.platforms_factory or GatewayPlatforms
                    self.platforms = factory(self.store, configs, emit=self.emit)
                    self.platforms.start()
                self.running_config = value
                self.emit("[多实例管理] 网关启动成功；平台=" + (",".join(value["platforms"]) or "未接入平台"))
            except BaseException:
                self.stop()
                raise

    def stop(self):
        with self.lock:
            self.stopping = True
            try:
                if self.platforms is not None:
                    self.platforms.close()
                    if any(not t.idle for t in self.platforms.transports):
                        # Keep DB and server alive until callbacks can no longer touch them.
                        raise ValueError("平台仍在收尾，请稍后重试停止；未释放网关资源")
                    self.platforms = None
                if self.server is not None:
                    self.server.close()
                    self.server = None
                if self.store is not None:
                    self.store.close()
                    self.store = None
                if self.lease is not None:
                    self.lease.close()
                    self.lease = None
                self.platform_keys.clear()
                self.running_config = None
            finally:
                self.stopping = False

    def state(self):
        # Do not block Tk/status consumers on a network start/close operation.
        if not self.lock.acquire(blocking=False):
            return "处理中"
        try:
            if self.server is not None:
                return "运行中"
            try:
                with HostResourceLock(["gateway-store:" + str(self.directory.resolve()),
                                       "gateway-host:" + str(self.directory.resolve())], reentrant=False):
                    return "已停止"
            except HostResourceBusy:
                return "外部运行"
        finally:
            self.lock.release()

    def instances(self):
        path = self.directory / "remote_gateway.sqlite3"
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            rows = db.execute("SELECT id,name,scopes,run,seen,online,revoked FROM instances ORDER BY name,id").fetchall()
        now = time.time()
        return [dict(instance_id=i, name=n, scopes=json.loads(s), run_id=r, seen=seen,
                     state="已撤销" if revoked else "在线" if online and now - seen < 60 else "离线")
                for i, n, s, r, seen, online, revoked in rows]

    def create_pairing(self, scopes):
        with self.lock:
            if self.store is not None:
                return self.store.create_pairing(scopes)
            store = RemoteGatewayStore(self.directory, cipher=self.cipher)
            try:
                return store.create_pairing(scopes)
            finally:
                store.close()

    def revoke(self, instance_id):
        with self.lock:
            if not any(v["instance_id"] == instance_id for v in self.instances()):
                raise ValueError("实例不存在，请刷新列表")
            if self.store is not None:
                self.store.revoke(instance_id)
            else:
                store = RemoteGatewayStore(self.directory, cipher=self.cipher)
                try:
                    store.revoke(instance_id)
                finally:
                    store.close()
            self.emit("[多实例管理] 已撤销实例接入；实例=" + instance_id + "；未取消已准入业务")
