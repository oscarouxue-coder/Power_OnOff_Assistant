"""One authenticated project RPC per connection on an operator-confirmed VPN."""
import hmac
import json
import secrets
import ssl
import threading

from src.core.remote_gateway_transport import require_protected_endpoint
from src.models.remote_gateway import canonical, signature


class ProjectPeerTransport:
    def __init__(self, local, peers, listen, *, vpn, dispatch, certificate=None, private_key=None):
        self.local, self.peers, self.dispatch = local, peers, dispatch
        self.host, self.port = listen
        self.vpn = vpn
        self.ssl = None
        if certificate or private_key:
            self.ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl.load_cert_chain(certificate, private_key)
        require_protected_endpoint(self.host, bool(self.ssl), vpn)
        for peer in peers.values():
            require_protected_endpoint(peer['host'], peer.get('tls', False), vpn)
        self.condition = threading.Condition()
        self.stopped = False
        self.active = 0
        self.server = self.thread = None

    def start(self):
        from websockets.sync.server import serve
        self.server = serve(self._receive, self.host, self.port, ssl=self.ssl, max_size=256 * 1024,
                            open_timeout=3, close_timeout=1)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _receive(self, socket):
        from websockets.exceptions import ConnectionClosed
        with self.condition:
            if self.stopped:
                return
            self.active += 1
        try:
            nonce = secrets.token_hex(32)
            socket.send(canonical(dict(peer=self.local, nonce=nonce)))
            hello = json.loads(socket.recv(timeout=4))
            key = self.peers[hello['from']]['key']
            challenge = dict(server=self.local, client=hello['from'], nonce=nonce, challenge=hello['challenge'])
            socket.send(canonical(dict(proof=signature(key, challenge))))
            packet = json.loads(socket.recv(timeout=4))
            body, mac = packet['body'], packet['mac']
            if (body['from'] != hello['from'] or body['to'] != self.local or body['nonce'] != nonce or
                    not hmac.compare_digest(signature(key, body), mac)):
                return
            result = self.dispatch(body['from'], body['call'])
            reply = dict(nonce=nonce, request_mac=mac, result=result)
            socket.send(canonical(dict(body=reply, mac=signature(key, reply))))
        except (KeyError, TypeError, ValueError, OSError, ConnectionClosed):
            return
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def call(self, peer, payload):
        from websockets.sync.client import connect
        config = self.peers[peer]
        host = config['host']
        if ':' in host:
            host = '[' + host + ']'
        scheme = 'wss' if config.get('tls') else 'ws'
        with connect(f"{scheme}://{host}:{config['port']}", open_timeout=2, close_timeout=1,
                     max_size=256 * 1024, proxy=None) as socket:
            hello = json.loads(socket.recv(timeout=3))
            if hello['peer'] != peer:
                raise ValueError('对端实例身份已变化')
            challenge = dict(server=peer, client=self.local, nonce=hello['nonce'], challenge=secrets.token_hex(32))
            socket.send(canonical({'from': self.local, 'challenge': challenge['challenge']}))
            proof = json.loads(socket.recv(timeout=3))
            if not hmac.compare_digest(proof['proof'], signature(config['key'], challenge)):
                raise ValueError('对端实例认证失败')
            body = dict(nonce=hello['nonce'], **{'from': self.local, 'to': peer, 'call': payload})
            key = config['key']
            mac = signature(key, body)
            socket.send(canonical(dict(body=body, mac=mac)))
            reply = json.loads(socket.recv(timeout=5))
            value = reply['body']
            if (value['nonce'] != hello['nonce'] or value['request_mac'] != mac or
                    not hmac.compare_digest(signature(key, value), reply['mac'])):
                raise ValueError('对端回执认证失败')
            return value['result']

    def close(self):
        with self.condition:
            self.stopped = True
        if self.server:
            self.server.shutdown()
        if self.thread and self.thread.ident is not None:
            self.thread.join()
        with self.condition:
            self.condition.wait_for(lambda: not self.active)

