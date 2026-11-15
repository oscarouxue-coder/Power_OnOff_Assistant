"""锁定飞书SDK的真实Protobuf/分片/ACK与线程生命周期，使用离线WebSocket。"""
import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.feishu_stream import FeishuStream
from test_feishu_remote import incoming


@unittest.skipUnless(importlib.util.find_spec("lark_oapi"), "需要requirements中的锁定飞书SDK")
class StreamTests(unittest.TestCase):
    def setUp(self):
        self.sdk = importlib.import_module("lark_oapi.ws.client")
        self.api = Mock()
        self.api.bot_id.return_value = "bot1"
        self.api.endpoint.return_value = {"URL": "wss://msg-frontier.feishu.cn/ws/v2?device_id=offline&service_id=1"}
        self.received, self.statuses = [], []
        self.streams = []
        self.addCleanup(self.close_streams)

    def close_streams(self):
        for stream in self.streams:
            stream.begin_close()
        for stream in self.streams:
            if stream.thread:
                stream.thread.join(5)
            self.assertTrue(stream.idle)

    def frame(self, payload, seq=0, total=1):
        frame = self.sdk.Frame()
        frame.method = self.sdk.FrameType.DATA.value
        frame.service = 1
        frame.SeqID = seq
        frame.LogID = 1
        for key, value in dict(type="event", message_id="transport-message", trace_id="trace", sum=str(total), seq=str(seq)).items():
            header = frame.headers.add()
            header.key, header.value = key, value
        frame.payload = payload
        return frame.SerializeToString()

    def socket(self, frames):
        sdk = self.sdk
        class Socket:
            def __init__(self):
                self.frames = list(frames)
                self.sent, self.codes = [], []
                self.ack = threading.Event()
                self.closed = False

            async def recv(self):
                if self.frames:
                    return self.frames.pop(0)
                await asyncio.sleep(3600)

            async def send(self, data):
                self.sent.append(data)
                frame = sdk.Frame()
                frame.ParseFromString(data)
                if frame.payload:
                    self.codes.append(json.loads(frame.payload)["code"])
                    self.ack.set()

            async def close(self):
                self.closed = True
        return Socket()

    def start(self, socket, receive=None):
        async def connect(*args, **kwargs):
            return socket
        stream = FeishuStream("cli_app1", "app-secret", receive or (lambda data, bot: self.received.append((data, bot))),
                              self.statuses.append, api=self.api)
        self.streams.append(stream)
        patcher = patch.object(self.sdk.websockets, "connect", side_effect=connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        stream.start()
        return stream

    def test_actual_sdk_fragment_merge_callback_and_200_ack(self):
        payload = json.dumps(incoming(), ensure_ascii=False).encode("utf-8")
        split = len(payload) // 2
        socket = self.socket([self.frame(payload[:split], 0, 2), self.frame(payload[split:], 1, 2)])
        stream = self.start(socket)
        self.assertTrue(socket.ack.wait(5), self.statuses)
        self.assertEqual(socket.codes, [200])
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0][0]["header"]["app_id"], "cli_app1")
        self.assertEqual(self.received[0][1], "bot1")
        stream.begin_close()
        stream.thread.join(5)
        self.assertTrue(stream.idle)
        self.assertTrue(socket.closed)
        self.assertTrue(stream.loop.is_closed())

    def test_persistence_failure_returns_500_for_redelivery(self):
        socket = self.socket([self.frame(json.dumps(incoming()).encode("utf-8"))])
        stream = self.start(socket, Mock(side_effect=RuntimeError("database busy private-ticket")))
        self.assertTrue(socket.ack.wait(5), self.statuses)
        self.assertEqual(socket.codes, [500])
        self.assertNotIn("private-ticket", str(self.statuses))

    def test_unsupported_event_value_error_is_acknowledged_without_dispatch(self):
        socket = self.socket([self.frame(json.dumps(incoming()).encode("utf-8"))])
        self.start(socket, Mock(side_effect=ValueError("unsupported")))
        self.assertTrue(socket.ack.wait(5), self.statuses)
        self.assertEqual(socket.codes, [200])

    def test_sdk_reenable_uses_new_loop_and_closes_all_old_tasks(self):
        for _ in range(2):
            socket = self.socket([self.frame(json.dumps(incoming()).encode("utf-8"))])
            stream = self.start(socket)
            self.assertTrue(socket.ack.wait(5), self.statuses)
            stream.begin_close()
            stream.thread.join(5)
            self.assertTrue(stream.idle)
            self.assertTrue(stream.loop.is_closed())
        self.assertIsNot(self.streams[0].loop, self.streams[1].loop)

    def test_untrusted_endpoint_is_rejected_before_socket_connect(self):
        for url in ("ws://msg-frontier.feishu.cn/ws", "wss://attacker.test/ws?ticket=private",
                    "wss://evilfeishu.cn/ws", "wss://user:private@msg-frontier.feishu.cn/ws"):
            self.api.endpoint.return_value = {"URL": url}
            stream = FeishuStream("cli_app1", "secret", Mock(), Mock(), api=self.api)
            with self.assertRaises(RuntimeError) as error:
                stream._endpoint(Mock(), self.sdk)
            self.assertNotIn("private", str(error.exception))

    def test_disconnect_reconnects_without_reusing_old_socket(self):
        first = self.socket([])
        async def fail():
            raise RuntimeError("private-socket-ticket")
        first.recv = fail
        second = self.socket([self.frame(json.dumps(incoming()).encode("utf-8"))])
        sockets = [first, second]
        async def connect(*args, **kwargs):
            return sockets.pop(0)
        stream = FeishuStream("cli_app1", "app-secret", lambda *args: self.received.append(args),
                              self.statuses.append, api=self.api)
        self.streams.append(stream)
        with patch.object(self.sdk.websockets, "connect", side_effect=connect) as connector:
            stream.start()
            self.assertTrue(second.ack.wait(5), self.statuses)
            stream.begin_close()
            stream.thread.join(5)
        self.assertEqual(connector.call_count, 2)
        self.assertTrue(first.closed)
        self.assertNotIn("private-socket-ticket", str(self.statuses))

    def test_stop_during_api_request_does_not_start_websocket_afterward(self):
        entered, release = threading.Event(), threading.Event()
        def bot():
            entered.set()
            release.wait(3)
            return "bot1"
        self.api.bot_id.side_effect = bot
        stream = FeishuStream("cli_app1", "app-secret", Mock(), self.statuses.append, api=self.api)
        self.streams.append(stream)
        with patch.object(self.sdk.websockets, "connect") as connect:
            stream.start()
            self.assertTrue(entered.wait(3))
            stream.begin_close()
            release.set()
            stream.thread.join(5)
            connect.assert_not_called()
        self.assertTrue(stream.idle)


if __name__ == "__main__":
    unittest.main()
