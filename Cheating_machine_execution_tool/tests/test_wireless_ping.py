"""不发网络包的无线Ping回归：双绑定、4包策略、包匹配和取消。"""
import ctypes as C
import socket
import struct
import threading
import unittest
from unittest.mock import Mock, patch

from src.core.wireless_ip import (validate_ping_target, validate_remote_ipv4, resolve_ipv4,
                                  DnsRequest, DnsResult, DnsRecord, _pending_dns)
from src.core.wireless_ping import (run_wireless_ping, echo_request, valid_reply, checksum,
                                    preflight_raw_socket)
from src.models.wifi_test_models import WifiInterface, WifiEnvironmentError, WifiCancelled, WifiVerificationError
from test_wifi_connection_service import VirtualEvent


INTERFACE = WifiInterface('interface-guid', 'Wi-Fi', 7)
ADAPTERS = [dict(guid='interface-guid', name='Wi-Fi', index=7, up=True, addresses=(('192.0.2.2', 24),)),
            dict(guid='wired', name='Ethernet', index=3, up=True, addresses=(('198.51.100.2', 24),))]


def reply_packet(request, source='192.0.2.1', destination='192.0.2.2'):
    icmp = bytearray(request)
    icmp[0:4] = b'\x00\x00\x00\x00'
    icmp[2:4] = struct.pack('!H', checksum(bytes(icmp)))
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(icmp), 1, 0, 64, 1, 0,
                         socket.inet_aton(source), socket.inet_aton(destination))
    return header + icmp


class FakeSocket:
    def __init__(self, event, successes=(1, 2, 3, 4), raw=True):
        self.event = event
        self.successes = successes
        self.raw = raw
        self.sent = []
        self.binding = None
        self.options = []
        self.timeout = 0.2
        self.answer_sent = False
        self.unrelated = False
        self.fail_bind = False
        self.fail_option = False
        self.fail_send = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def bind(self, address):
        if self.fail_bind:
            raise OSError(10049, 'bind failure')
        self.binding = address

    def setsockopt(self, *args):
        if self.fail_option:
            raise OSError(10022, 'binding unavailable')
        self.options.append(args)

    def connect(self, address):
        self.remote = address

    def getsockname(self):
        return self.binding

    def settimeout(self, seconds):
        self.timeout = seconds

    def sendto(self, data, address):
        if self.fail_send:
            raise OSError(10051, 'no wireless route')
        self.sent.append((data, address))
        self.answer_sent = False

    def recvfrom(self, _size):
        seq = len(self.sent)
        self.event.now += min(self.timeout, 0.01 if seq in self.successes else self.timeout)
        if seq in self.successes and not self.answer_sent:
            self.answer_sent = True
            request, target = self.sent[-1]
            source = '198.51.100.1' if self.unrelated else target[0]
            return reply_packet(request, source), (source, 0)
        raise socket.timeout()


class WirelessPingTests(unittest.TestCase):
    def setUp(self):
        self.event = VirtualEvent()
        self.raw = FakeSocket(self.event)
        self.route = FakeSocket(self.event, raw=False)
        self.logs = []
        self.guard = Mock()
        self.resolver = Mock(return_value=('203.0.113.1', '203.0.113.2'))

    def run_ping(self, target='192.0.2.1', provider=lambda: ADAPTERS, **changes):
        factory = Mock(side_effect=lambda _af, kind, _proto: self.raw if kind == socket.SOCK_RAW else self.route)
        args = dict(interface=INTERFACE, target=target, stop=self.event, emit=self.logs.append,
                    guard=self.guard, adapter_provider=provider, resolver=self.resolver,
                    socket_factory=factory, clock=lambda: self.event.now)
        args.update(changes)
        result = run_wireless_ping(**args)
        self.factory = factory
        return result

    def test_four_packets_bind_wireless_source_and_interface_and_report_statistics(self):
        result = self.run_ping()
        self.assertTrue(result.ok)
        self.assertEqual(result.sent, 4)
        self.assertEqual(len(result.times_ms), 4)
        self.assertEqual(self.raw.binding, ('192.0.2.2', 0))
        self.assertEqual(self.route.binding, self.raw.binding)
        self.assertIn((socket.IPPROTO_IP, 31, struct.pack('!I', 7)), self.raw.options)
        self.assertIn('丢包率=0%', '\n'.join(self.logs))
        self.assertIn('min/avg/max', '\n'.join(self.logs))
        self.resolver.assert_not_called()

    def test_one_reply_passes_but_all_four_probes_still_run(self):
        self.raw.successes = (2,)
        result = self.run_ping()
        self.assertTrue(result.ok)
        self.assertEqual(len(self.raw.sent), 4)
        self.assertEqual(len(result.times_ms), 1)
        self.assertIn('丢包率=75%', '\n'.join(self.logs))

    def test_no_replies_fails_without_reconnection_or_default_interface(self):
        self.raw.successes = ()
        self.assertFalse(self.run_ping().ok)
        self.assertEqual(len(self.raw.sent), 4)
        self.assertLessEqual(self.event.now, 11.01)

    def test_hostname_resolves_on_wireless_and_pins_first_a_record(self):
        result = self.run_ping('example.test')
        self.resolver.assert_called_once_with('example.test', 7, self.event, self.guard)
        self.assertEqual(result.target_ip, '203.0.113.1')
        self.assertTrue(all(address[0] == '203.0.113.1' for _, address in self.raw.sent))

    def test_wrong_source_reply_not_counted(self):
        self.raw.unrelated = True
        self.assertFalse(self.run_ping().ok)

    def test_interface_option_failure_never_sends_or_falls_back(self):
        self.raw.fail_option = True
        with self.assertRaises(WifiEnvironmentError):
            self.run_ping()
        self.assertEqual(self.raw.sent, [])

    def test_wireless_unreachable_does_not_use_reachable_wired_interface(self):
        self.raw.fail_send = True
        with self.assertRaises(WifiEnvironmentError):
            self.run_ping()
        self.assertEqual(self.raw.binding[0], '192.0.2.2')
        self.assertEqual(self.raw.sent, [])

    def test_dns_failure_prevents_all_icmp_packets(self):
        self.resolver.side_effect = WifiEnvironmentError('DNS failure')
        with self.assertRaises(WifiEnvironmentError):
            self.run_ping('example.test')
        self.assertEqual(self.raw.sent, [])

    def test_waits_for_wireless_ip_not_other_interface(self):
        provider = Mock(return_value=[ADAPTERS[1]])
        with self.assertRaises(WifiEnvironmentError):
            self.run_ping(provider=provider)
        self.assertGreaterEqual(self.event.now, 30)
        self.assertEqual(self.raw.sent, [])

    def test_cancel_during_ipv4_wait_and_during_reply_wait(self):
        self.event.on_wait = self.event.set
        with self.assertRaises(WifiCancelled):
            self.run_ping(provider=lambda: [])
        self.event = VirtualEvent()
        self.raw.event = self.route.event = self.event
        self.raw.successes = ()
        self.guard.side_effect = lambda: self.event.set() if self.raw.sent else None
        with self.assertRaises(WifiCancelled):
            self.run_ping()
        self.assertEqual(len(self.raw.sent), 1)

    def test_changed_bssid_after_reply_does_not_produce_success(self):
        def guard():
            if self.raw.sent and self.raw.answer_sent:
                raise WifiVerificationError('BSSID changed')
        self.guard.side_effect = guard
        with self.assertRaises(WifiVerificationError):
            self.run_ping()
        self.assertFalse(any('无线Ping汇总' in line for line in self.logs))

    def test_lost_source_address_stops_later_packets(self):
        provider = lambda: ADAPTERS if not self.raw.sent else [ADAPTERS[1]]
        with self.assertRaises(WifiEnvironmentError):
            self.run_ping(provider=provider)
        self.assertEqual(len(self.raw.sent), 1)

    def test_local_ip_and_subnet_broadcast_not_counted_as_wireless_connectivity(self):
        for target in ('192.0.2.2', '198.51.100.2', '192.0.2.255'):
            with self.subTest(target=target), self.assertRaises(WifiEnvironmentError):
                self.run_ping(target)
        self.assertEqual(self.raw.sent, [])

    def test_permission_preflight_is_explicit(self):
        with self.assertRaisesRegex(WifiEnvironmentError, '管理员'):
            preflight_raw_socket(Mock(side_effect=PermissionError()))


class TargetAndPacketTests(unittest.TestCase):
    def test_ipv4_domain_idna_and_invalid_targets(self):
        for value in ('192.168.1.1', 'example.com', 'host-name.test.'):
            self.assertTrue(validate_ping_target(value))
        self.assertTrue(validate_ping_target('例子.测试').startswith('xn--'))
        for value in ('', '127.0.0.1', '224.0.0.1', '0.0.0.0', '255.255.255.255',
                      'http://example.com', 'example.com:80', '::1', '999.1.1.1',
                      'localhost', 'x.localhost', 'a b.test', 'x;whoami'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_ping_target(value)

    def test_echo_reply_requires_ip_id_sequence_payload_and_checksum(self):
        request = echo_request(12, 3, b'nonce')
        valid = reply_packet(request)
        self.assertEqual(checksum(request), 0)
        self.assertTrue(valid_reply(valid, '192.0.2.1', '192.0.2.2', 12, 3, b'nonce'))
        for packet, identifier, seq, payload in ((valid, 13, 3, b'nonce'), (valid, 12, 2, b'nonce'),
                                                (valid, 12, 3, b'other'), (valid[:-1], 12, 3, b'nonce'),
                                                (valid[:-1] + b'X', 12, 3, b'nonce'),
                                                (b'', 12, 3, b'nonce')):
            self.assertFalse(valid_reply(packet, '192.0.2.1', '192.0.2.2', identifier, seq, payload))


class FakeFunction:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class DnsTests(unittest.TestCase):
    def test_stop_before_dns_submission_never_queries_and_releases_buffers(self):
        import types
        stop = threading.Event()
        query = Mock()
        api = types.SimpleNamespace(DnsQueryEx=FakeFunction(query), DnsCancelQuery=FakeFunction(lambda _: 0),
                                    DnsRecordListFree=FakeFunction(lambda *_: None))
        with patch('src.core.wireless_ip.C.WinDLL', return_value=api):
            with self.assertRaises(WifiCancelled):
                resolve_ipv4('example.test', 7, stop, stop.set)
        query.assert_not_called()
        self.assertFalse(_pending_dns)

    def test_dns_timeout_cancels_query_without_default_interface_fallback(self):
        import types
        pending = {}
        event = VirtualEvent()
        stop = threading.Event()
        callback_type = C.WINFUNCTYPE(None, C.c_void_p, C.POINTER(DnsResult))
        def query(req, result, _cancel):
            request = C.cast(req, C.POINTER(DnsRequest)).contents
            self.assertEqual(request.index, 7)
            pending['callback'] = C.cast(request.callback, callback_type)
            pending['result'] = C.cast(result, C.POINTER(DnsResult))
            return 9506
        cancel = Mock(return_value=0)
        api = types.SimpleNamespace(DnsQueryEx=FakeFunction(query), DnsCancelQuery=FakeFunction(cancel),
                                    DnsRecordListFree=FakeFunction(lambda *_: None))
        with patch('src.core.wireless_ip.C.WinDLL', return_value=api), \
                patch('src.core.wireless_ip.threading.Event', return_value=event):
            with self.assertRaisesRegex(WifiEnvironmentError, '超时'):
                resolve_ipv4('example.test', 7, stop, lambda: None, clock=lambda: event.now)
            cancel.assert_called_once()
            pending['callback'](None, pending['result'])
        self.assertFalse(_pending_dns)

    def test_native_dns_uses_explicit_interface_and_first_a_record(self):
        import types
        records = (DnsRecord * 2)()
        for record, address in zip(records, ('203.0.113.2', '203.0.113.1')):
            record.type, record.length = 1, 4
            record.data[:] = socket.inet_aton(address)
        records[0].next = C.pointer(records[1])
        captured = {}
        def query(req, result, _cancel):
            request = C.cast(req, C.POINTER(DnsRequest)).contents
            captured['index'] = request.index
            captured['name'] = request.name
            C.cast(result, C.POINTER(DnsResult)).contents.records = C.pointer(records[0])
            return 0
        api = types.SimpleNamespace(DnsQueryEx=FakeFunction(query), DnsCancelQuery=FakeFunction(lambda _: 0),
                                    DnsRecordListFree=FakeFunction(lambda *_: None))
        with patch('src.core.wireless_ip.C.WinDLL', return_value=api):
            result = resolve_ipv4('example.test', 7, threading.Event(), lambda: None)
        self.assertEqual(result, ('203.0.113.2', '203.0.113.1'))
        self.assertEqual(captured, {'index': 7, 'name': 'example.test.'})
        self.assertFalse(_pending_dns)

    def test_dns_pending_cancellation_retains_buffers_until_completion(self):
        import types
        pending = {}
        callback_type = C.WINFUNCTYPE(None, C.c_void_p, C.POINTER(DnsResult))
        stop = threading.Event()
        def query(req, result, cancel):
            pending['callback'] = C.cast(C.cast(req, C.POINTER(DnsRequest)).contents.callback, callback_type)
            pending['result'] = C.cast(result, C.POINTER(DnsResult))
            stop.set()
            return 9506
        cancel = Mock(return_value=0)
        api = types.SimpleNamespace(DnsQueryEx=FakeFunction(query), DnsCancelQuery=FakeFunction(cancel),
                                    DnsRecordListFree=FakeFunction(lambda *_: None))
        with patch('src.core.wireless_ip.C.WinDLL', return_value=api):
            with self.assertRaises(WifiCancelled):
                resolve_ipv4('example.test', 7, stop, lambda: None)
            self.assertTrue(_pending_dns)
            cancel.assert_called_once()
            pending['callback'](None, pending['result'])
        self.assertFalse(_pending_dns)


if __name__ == '__main__':
    unittest.main()
