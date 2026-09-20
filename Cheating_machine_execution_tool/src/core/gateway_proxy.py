"""Per-channel HTTP proxy restricted to one gateway and one source interface."""
import ipaddress
import os
import select
import socket
import socketserver
import threading
import time
from urllib.parse import urlsplit
from html.parser import HTMLParser


class _UpgradeFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.file = False
        self.update = False
        self.in_button = False

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "input":
            self.file |= attributes.get("type", "").lower() == "file"
            self.update |= attributes.get("value", "").strip().lower() == "update software"
        if tag == "button":
            self.in_button = True

    def handle_endtag(self, tag):
        if tag == "button":
            self.in_button = False

    def handle_data(self, data):
        if self.in_button and data.strip().lower() == "update software":
            self.update = True


class GatewayProxy:
    def __init__(self, source_ip, interface_index, target_ip, log, target_port=80):
        self.source_ip = str(ipaddress.IPv4Address(source_ip))
        self.target_ip = str(ipaddress.IPv4Address(target_ip))
        self.interface_index = interface_index
        self.target_port = target_port
        self.log = log
        self.server = None
        self.stop_event = threading.Event()
        self.sockets = set()
        self.lock = threading.Lock()

    def _connect(self, timeout=15):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.bind((self.source_ip, 0))
            if os.name == "nt":
                # Fail closed: never silently drop the requested interface.
                sock.setsockopt(socket.IPPROTO_IP, getattr(socket, "IP_UNICAST_IF", 31),
                                socket.htonl(self.interface_index))
            sock.connect((self.target_ip, self.target_port))
            return sock
        except Exception:
            sock.close()
            raise

    def start(self):
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                owner._handle(self.request)

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()
        return self.server.server_address[1]

    def _probe_upgrade_page(self, timeout):
        """Read-only GET through exactly the same bound socket as the browser."""
        deadline = time.monotonic() + timeout
        with self._connect(timeout=timeout) as sock:
            sock.sendall((f"GET / HTTP/1.0\r\nHost: {self.target_ip}\r\n"
                          "Connection: close\r\n\r\n").encode())
            data = bytearray()
            while len(data) < 65536:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("读取升级页面超时")
                sock.settimeout(remaining)
                part = sock.recv(min(4096, 65536 - len(data)))
                if not part:
                    break
                data.extend(part)
                if data.startswith(b"HTTP/"):
                    if b"\r\n\r\n" not in data:
                        continue
                    header, body = data.split(b"\r\n\r\n", 1)
                    status = header.split(b"\r\n", 1)[0].split()
                    if len(status) < 2 or status[1] != b"200":
                        raise RuntimeError(f"升级页面尚未就绪：{status[:2]}")
                else:
                    body = data
                parser = _UpgradeFormParser()
                parser.feed(body.decode("utf-8", errors="replace"))
                if parser.file and parser.update:
                    return
            raise RuntimeError("尚未返回文件选择框和 Update software")

    def wait_for_gateway(self, timeout=90, *, clock=time.monotonic, sleep_fn=time.sleep):
        deadline = clock() + timeout
        last_error = "尚未尝试"
        last_log = -10.0
        self.log(f"等待网关Web升级页面就绪（最长{timeout:g}秒），出口 {self.source_ip} / ifIndex {self.interface_index}。")
        while not self.stop_event.is_set():
            remaining = deadline - clock()
            if remaining <= 0:
                break
            try:
                self._probe_upgrade_page(min(3, remaining))
                self.log("网关Web升级页面已就绪，开始打开浏览器。")
                return
            except (OSError, RuntimeError) as exc:
                last_error = str(exc)
                if clock() - last_log >= 5:
                    self.log(f"网关Web尚未就绪，继续只读重试：{last_error}")
                    last_log = clock()
            remaining = deadline - clock()
            if remaining > 0:
                sleep_fn(min(1, remaining))
        raise TimeoutError(f"等待网关Web升级页面就绪失败（{timeout:g}秒，源 {self.source_ip} / ifIndex {self.interface_index} → {self.target_ip}:{self.target_port}）：{last_error}")

    def _handle(self, client):
        upstream = None
        stage = "等待浏览器请求头"
        method = ""
        response_started = False
        with self.lock:
            self.sockets.add(client)
        try:
            client.settimeout(15)
            packet = bytearray()
            while b"\r\n\r\n" not in packet:
                data = client.recv(4096)
                if not data:
                    return
                packet.extend(data)
                if len(packet) > 128 * 1024:
                    raise ValueError("HTTP 请求头过大。")
            header, body = bytes(packet).split(b"\r\n\r\n", 1)
            lines = header.decode("iso-8859-1").split("\r\n")
            method, raw_url, version = lines[0].split(" ", 2)
            target = urlsplit(raw_url)
            if (target.scheme != "http" or target.hostname != self.target_ip
                    or (target.port or 80) != self.target_port or target.username or target.password):
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            stage = f"连接样机 {self.target_ip}:{self.target_port}"
            upstream = self._connect()
            with self.lock:
                self.sockets.add(upstream)
            path = target.path or "/"
            if target.query:
                path += "?" + target.query
            # Force one HTTP request per TCP connection, so a persistent proxy
            # connection cannot forward a second absolute URL to another host.
            filtered = [line for line in lines[1:] if line.partition(":")[0].lower()
                        not in ("connection", "proxy-connection", "proxy-authorization", "host")]
            request_header = [f"{method} {path} {version}",
                              f"Host: {self.target_ip}:{self.target_port}", *filtered, "Connection: close", "", ""]
            stage = "向样机发送请求"
            upstream.sendall("\r\n".join(request_header).encode("iso-8859-1") + body)
            self.log(f"Web TX {method} {path}，出口 {self.source_ip} / ifIndex {self.interface_index}")
            deadline = time.monotonic() + 600
            first_response = bytearray()
            stage = "转发样机响应/浏览器数据"
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                readable, _, _ = select.select([client, upstream], [], [], 0.2)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    if source is upstream and not response_started:
                        first_response.extend(data)
                        if len(first_response) < 5:
                            continue
                        if not first_response.startswith(b"HTTP/"):
                            if method != "GET" or not first_response.lstrip().startswith(b"<"):
                                raise ValueError("样机返回非HTTP响应，已停止转发。")
                            # Some boot HTTP servers return HTTP/0.9-style HTML.
                            client.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n")
                            self.log("Web 样机返回无HTTP头的HTML，已兼容转发升级页面。")
                        data = bytes(first_response)
                        response_started = True
                    (upstream if source is client else client).sendall(data)
        except (OSError, ValueError) as exc:
            if not self.stop_event.is_set():
                # Chromium may preconnect without ever sending a request.
                if stage == "等待浏览器请求头" and isinstance(exc, TimeoutError):
                    return
                self.log(f"Web 代理失败（{stage}，源 {self.source_ip} / ifIndex {self.interface_index}）：{exc}")
                try:
                    if not response_started:
                        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                except OSError:
                    pass
        finally:
            with self.lock:
                self.sockets.discard(client)
                if upstream:
                    self.sockets.discard(upstream)
            if upstream:
                upstream.close()

    def close(self):
        self.stop_event.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None
        with self.lock:
            sockets = list(self.sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except OSError:
                pass
