"""Authenticated WebSocket relay transport. Connection loss never touches business jobs."""
import ipaddress
import json
import random
import secrets
import threading
import time
from urllib.parse import urlsplit

from src.models.remote_gateway import SignedChannel, canonical, signature


def require_protected_endpoint(host, secure, vpn):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if secure:
            return
        raise ValueError("非TLS入口必须使用明确的回环/VPN IP地址") from None
    if address.is_loopback:
        return
    if not secure and not (vpn and address.is_private and not address.is_unspecified):
        raise ValueError("跨网连接要求WSS或明确确认的私有VPN地址")
    if address.is_unspecified:
        raise ValueError("必须绑定明确地址，不绑定所有接口")


class GatewayWebSocketServer:
    def __init__(self, store, host="127.0.0.1", port=0, *, ssl_context=None, vpn=False, emit=lambda line: None):
        require_protected_endpoint(host, ssl_context is not None, vpn)
        self.store, self.host, self.port = store, host, port
        self.ssl_context, self.emit = ssl_context, emit
        self.stop = threading.Event()
        self.guard = threading.RLock()
        self.connections = {}
        self.server = self.thread = None

    def start(self):
        from websockets.sync.server import serve
        from src.core.host_resource_lock import HostResourceLock
        self.lease = HostResourceLock(["gateway-store:" + str(self.store.directory.resolve())], reentrant=False).acquire()
        try:
            self.store.recover()
            self.server = serve(self._connection, self.host, self.port, ssl=self.ssl_context,
                                max_size=512 * 1024, open_timeout=10, close_timeout=2,
                                ping_interval=15, ping_timeout=20)
        except BaseException:
            self.lease.close()
            raise
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="relay-gateway", daemon=True)
        self.thread.start()
        self.emit("[统一网关] 已监听认证入口：" + self.host + ":" + str(self.port))
        return self

    def _connection(self, socket):
        instance_id = run_id = None
        owned = False
        try:
            nonce = secrets.token_urlsafe(32)
            socket.send(canonical(dict(version=1, nonce=nonce)))
            hello = json.loads(socket.recv(timeout=10))
            if hello.get("op") == "pair":
                if set(hello) != {"op", "code", "instance_id", "name"}:
                    raise ValueError("配对字段无效")
                result = self.store.pair(hello["code"], hello["instance_id"], hello["name"])
                socket.send(canonical(dict(ok=True, pairing=result)))
                return
            if set(hello) != {"op", "instance_id", "run_id", "proof"} or hello["op"] != "hello":
                raise ValueError("连接身份字段无效")
            instance_id, run_id = hello["instance_id"], hello["run_id"]
            secret = self.store.credential(instance_id)
            import hmac
            expected = signature(secret, dict(nonce=nonce, instance_id=instance_id, run_id=run_id))
            if not isinstance(hello["proof"], str) or not hmac.compare_digest(hello["proof"], expected):
                raise ValueError("连接认证失败")
            with self.guard:
                if instance_id in self.connections:
                    raise ValueError("同一实例已有活动连接")
                self.store.register(instance_id, run_id)
                self.connections[instance_id] = socket
                owned = True
            channel = SignedChannel(secret, nonce, "gateway")
            socket.send(canonical(channel.pack(dict(ok=True))))
            while not self.stop.is_set():
                value = channel.unpack(json.loads(socket.recv(timeout=35)))
                self.store.credential(instance_id)  # Revocation is effective on the next frame.
                operation = value.get("op")
                if operation == "poll" and set(value) == {"op"}:
                    response = dict(ok=True, requests=self.store.poll(instance_id, run_id))
                elif operation == "receipt" and set(value) == {"op", "request_id", "receipt"}:
                    self.store.acknowledge(instance_id, run_id, value["request_id"], value["receipt"])
                    response = dict(ok=True)
                else:
                    raise ValueError("未开放的转发操作")
                socket.send(canonical(channel.pack(response)))
        except Exception:
            self.emit("[统一网关] 连接结束或认证/收发异常（凭据省略）；未重发业务请求")
        finally:
            if owned:
                with self.guard:
                    if self.connections.get(instance_id) is socket:
                        self.connections.pop(instance_id, None)
                        self.store.offline(instance_id, run_id)

    def close(self):
        self.stop.set()
        with self.guard:
            sockets = list(self.connections.values())
        for socket in sockets:
            socket.close()
        if self.server:
            self.server.shutdown()
        if self.thread:
            self.thread.join(5)
        if getattr(self, "lease", None):
            self.lease.close()


class GatewayConnection:
    def __init__(self, url, *, vpn=False):
        parts = urlsplit(url)
        if parts.scheme not in ("ws", "wss") or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
            raise ValueError("入口须为不含凭据和查询参数的WS/WSS地址")
        require_protected_endpoint(parts.hostname, parts.scheme == "wss", vpn)
        self.url, self.socket, self.channel = url, None, None

    def _open(self):
        from websockets.sync.client import connect
        self.socket = connect(self.url, open_timeout=10, close_timeout=2, max_size=512 * 1024,
                              ping_interval=15, ping_timeout=20, proxy=None)
        challenge = json.loads(self.socket.recv(timeout=10))
        if challenge.get("version") != 1 or not isinstance(challenge.get("nonce"), str):
            raise ValueError("网关协议不匹配")
        return challenge["nonce"]

    def pair(self, code, instance_id, name):
        self._open()
        try:
            self.socket.send(canonical(dict(op="pair", code=code, instance_id=instance_id, name=name)))
            return json.loads(self.socket.recv(timeout=10))["pairing"]
        finally:
            self.close()

    def connect(self, instance_id, run_id, credential):
        nonce = self._open()
        body = dict(nonce=nonce, instance_id=instance_id, run_id=run_id)
        self.socket.send(canonical(dict(op="hello", instance_id=instance_id, run_id=run_id, proof=signature(credential, body))))
        self.channel = SignedChannel(credential, nonce, "instance")
        self.channel.unpack(json.loads(self.socket.recv(timeout=10)))
        return self

    def call(self, payload):
        self.socket.send(canonical(self.channel.pack(payload)))
        return self.channel.unpack(json.loads(self.socket.recv(timeout=10)))

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None


class GatewayInstanceClient:
    """Transport and Agent worker have independent lifetimes; close stops relay only."""
    def __init__(self, url, credential, bridge, *, vpn=False, emit=lambda line: None, poll_interval=.25):
        self.url, self.credential, self.bridge = url, credential, bridge
        self.vpn, self.emit, self.interval = vpn, emit, poll_interval
        self.stop = threading.Event()
        self.connection = None
        self.network = self.worker = None
        self.connected = threading.Event()

    def start(self):
        self.network = threading.Thread(target=self._network, name="relay-client", daemon=True)
        self.worker = threading.Thread(target=self._worker, name="relay-agent-inbox", daemon=True)
        self.worker.start()
        self.network.start()
        return self

    def _worker(self):
        while not self.stop.wait(.05):
            try:
                self.bridge.process_one()
            except Exception:
                self.emit("[统一接入] 收件处理异常；未自动重新执行")

    def _network(self):
        delay = 1
        exported = {}
        while not self.stop.is_set():
            try:
                self.connection = GatewayConnection(self.url, vpn=self.vpn)
                identity = self.bridge.identity
                self.connection.connect(identity.instance_id, identity.run_id, self.credential)
                self.connected.set()
                self.emit("[统一接入] 已认证连接；恢复原请求确认，不重放业务")
                exported.clear()
                delay = 1
                while not self.stop.is_set():
                    for request_id, receipt in self.bridge.export_receipts().items():
                        key = canonical(receipt)
                        if exported.get(request_id) != key:
                            self.connection.call(dict(op="receipt", request_id=request_id, receipt=receipt))
                            exported[request_id] = key
                    for request in self.connection.call(dict(op="poll"))["requests"]:
                        try:
                            receipt = self.bridge.receive(request)
                        except ValueError:
                            receipt = dict(state="rejected", request_id=request["request_id"],
                                           notice="目标实例拒绝本请求：请核对本地启用状态、来源和范围")
                        self.connection.call(dict(op="receipt", request_id=request["request_id"], receipt=receipt))
                    self.stop.wait(self.interval)
            except Exception:
                if not self.stop.is_set():
                    self.emit("[统一接入] 网关不可达/收发未确认，等待重连；已准入业务继续")
            finally:
                self.connected.clear()
                if self.connection:
                    self.connection.close()
                    self.connection = None
            if self.stop.wait(delay + random.random() * .2):
                break
            delay = min(30, delay * 2)

    def begin_close(self):
        self.stop.set()
        if self.connection:
            self.connection.close()

    @property
    def idle(self):
        return all(thread is None or not thread.is_alive() for thread in (self.network, self.worker))

    def close(self):
        self.begin_close()
        for thread in (self.network, self.worker):
            if thread:
                thread.join(12)
        # Do not close the Agent, its job database, its transports or its job stop tokens.
