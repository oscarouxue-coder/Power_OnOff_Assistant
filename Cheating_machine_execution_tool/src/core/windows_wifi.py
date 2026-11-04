"""Windows Native WLAN 的小范围封装；只建立未持久化的任务专属配置。"""
import ctypes as C
from ctypes import wintypes as W
import os
import struct
import threading
import uuid
from xml.sax.saxutils import escape

from src.models.wifi_test_models import (
    WifiInterface, WifiObservation, WifiConnection, WifiEnvironmentError,
)

U32 = C.c_uint32
U16 = C.c_uint16
U8 = C.c_ubyte
AUTH_NAMES = {1: '开放', 4: 'WPA-PSK', 7: 'WPA2-PSK', 9: 'WPA3-SAE'}
CIPHER_NAMES = {0: '无', 2: 'TKIP', 4: 'AES'}


class Guid(C.Structure):
    _fields_ = [('data1', U32), ('data2', U16), ('data3', U16), ('data4', U8 * 8)]

    @classmethod
    def parse(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)

    def text(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


class Ssid(C.Structure):
    _fields_ = [('length', U32), ('data', U8 * 32)]

    def text(self):
        if self.length > 32:
            raise WifiEnvironmentError('Windows返回无效SSID长度')
        return bytes(self.data[:self.length]).decode('utf-8', 'replace')


class InterfaceInfo(C.Structure):
    _fields_ = [('guid', Guid), ('description', W.WCHAR * 256), ('state', U32)]


class RateSet(C.Structure):
    _fields_ = [('length', U32), ('rates', U16 * 126)]


class BssEntry(C.Structure):
    _fields_ = [('ssid', Ssid), ('phy_id', U32), ('bssid', U8 * 6),
                ('bss_type', U32), ('phy_type', U32), ('rssi', C.c_int32),
                ('quality', U32), ('in_domain', U8), ('beacon', U16),
                ('timestamp', C.c_uint64), ('host_timestamp', C.c_uint64),
                ('capability', U16), ('frequency', U32), ('rates', RateSet),
                ('ie_offset', U32), ('ie_size', U32)]


class Association(C.Structure):
    _fields_ = [('ssid', Ssid), ('bss_type', U32), ('bssid', U8 * 6),
                ('phy_type', U32), ('phy_index', U32), ('quality', U32),
                ('rx_rate', U32), ('tx_rate', U32)]


class Security(C.Structure):
    _fields_ = [('enabled', C.c_int32), ('one_x', C.c_int32), ('auth', U32), ('cipher', U32)]


class ConnectionAttributes(C.Structure):
    _fields_ = [('state', U32), ('mode', U32), ('profile', W.WCHAR * 256),
                ('association', Association), ('security', Security)]


class NdisHeader(C.Structure):
    _fields_ = [('type', U8), ('revision', U8), ('size', U16)]


class BssidList(C.Structure):
    _fields_ = [('header', NdisHeader), ('count', U32), ('total', U32), ('addresses', (U8 * 6) * 1)]


class ConnectionParameters(C.Structure):
    _fields_ = [('mode', U32), ('profile', W.LPCWSTR), ('ssid', C.POINTER(Ssid)),
                ('bssids', C.POINTER(BssidList)), ('bss_type', U32), ('flags', U32)]


class Notification(C.Structure):
    _fields_ = [('source', U32), ('code', U32), ('guid', Guid), ('size', U32), ('data', C.c_void_p)]


def security_pairs(ies, privacy):
    """解析目标 BSS 自身的 RSN/WPA IE，不把同名其它 AP 的安全参数混入。"""
    pairs = set()
    found_security = False
    pos = 0
    while pos + 2 <= len(ies):
        tag, size = ies[pos:pos + 2]
        data = ies[pos + 2:pos + 2 + size]
        pos += size + 2
        if len(data) != size:
            return ()
        if tag == 48:
            oui, auths = b'\x00\x0f\xac', {2: 7, 8: 9}
        elif tag == 221 and data.startswith(b'\x00\x50\xf2\x01'):
            data = data[4:]
            oui, auths = b'\x00\x50\xf2', {2: 4}
        else:
            continue
        found_security = True
        try:
            if data[:2] != b'\x01\x00':
                continue
            count = struct.unpack_from('<H', data, 6)[0]
            end = 8 + 4 * count
            ciphers = [data[i:i + 4] for i in range(8, end, 4)]
            count_auth = struct.unpack_from('<H', data, end)[0]
            if end + 2 + count_auth * 4 > len(data):
                return ()
            akms = [data[i:i + 4] for i in range(end + 2, end + 2 + 4 * count_auth, 4)]
            for cipher in ciphers:
                for akm in akms:
                    if cipher[:3] == oui and akm[:3] == oui and cipher[3] in (2, 4) and akm[3] in auths:
                        pairs.add((auths[akm[3]], cipher[3]))
        except (struct.error, IndexError):
            return ()
    if not privacy and not found_security:
        pairs.add((1, 0))
    return tuple(sorted(pairs))


def choose_security(observation, supported, source='auto', auth='WPA2-PSK', cipher='AES'):
    available = set(observation.pairs) & set(supported)
    if source == 'manual':
        auth_ids = {'None': {1}, 'WPA-PSK': {4}, 'WPA2-PSK': {7}, 'WPA3-PSK': {9},
                    'WPA-PSK/WPA2-PSK': {4, 7}, 'WPA-PSK/WPA2PSK': {4, 7},
                    'WPA2-PSK/WPA3-PSK': {7, 9}}.get(auth, set())
        cipher_ids = {0} if auth == 'None' else {'AES': {4}, 'TKIP': {2}, 'TKIP+AES': {2, 4}}.get(cipher, set())
        available &= {(a, c) for a in auth_ids for c in cipher_ids}
    for pair in ((9, 4), (7, 4), (4, 4), (7, 2), (4, 2), (1, 0)):
        if pair in available:
            return pair
    raise WifiEnvironmentError('目标网络、Windows/网卡能力与认证约束没有受支持的组合')


def profile_xml(name, target, pair):
    auth, cipher = pair
    auth_xml = {1: 'open', 4: 'WPAPSK', 7: 'WPA2PSK', 9: 'WPA3SAE'}[auth]
    cipher_xml = {0: 'none', 2: 'TKIP', 4: 'AES'}[cipher]
    key = ''
    if auth != 1:
        password = target.password
        raw_key = len(password) == 64 and all(ch in '0123456789abcdefABCDEF' for ch in password)
        if not (8 <= len(password) <= 63 or (raw_key and auth != 9)):
            raise WifiEnvironmentError('样机WiFi密码不符合所选认证方式的密钥要求')
        key = ('<sharedKey><keyType>' + ('networkKey' if raw_key else 'passPhrase') +
               '</keyType><protected>false</protected><keyMaterial>' + escape(password) +
               '</keyMaterial></sharedKey>')
    return ('<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
            '<name>' + escape(name) + '</name><SSIDConfig><SSID><hex>' + target.ssid.encode('utf-8').hex() +
            '</hex></SSID></SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual</connectionMode>'
            '<MSM><security><authEncryption><authentication>' + auth_xml + '</authentication><encryption>' +
            cipher_xml + '</encryption><useOneX>false</useOneX></authEncryption>' + key +
            '</security></MSM></WLANProfile>')


class NativeWifiBackend:
    def __init__(self):
        if os.name != 'nt':
            raise WifiEnvironmentError('无线测试仅支持Windows')
        self.api = C.WinDLL('wlanapi.dll')
        self.ip = C.WinDLL('iphlpapi.dll')
        self.handle = W.HANDLE()
        self._scan_event = threading.Event()
        self._scan_guid = None
        self._scan_failed = False
        self._callback = None
        P = C.c_void_p
        signatures = {
            'WlanOpenHandle': [U32, P, C.POINTER(U32), C.POINTER(W.HANDLE)],
            'WlanCloseHandle': [W.HANDLE, P], 'WlanFreeMemory': [P],
            'WlanEnumInterfaces': [W.HANDLE, P, C.POINTER(P)],
            'WlanQueryInterface': [W.HANDLE, C.POINTER(Guid), U32, P, C.POINTER(U32), C.POINTER(P), P],
            'WlanGetNetworkBssList': [W.HANDLE, C.POINTER(Guid), P, U32, W.BOOL, P, C.POINTER(P)],
            'WlanScan': [W.HANDLE, C.POINTER(Guid), P, P, P],
            'WlanConnect': [W.HANDLE, C.POINTER(Guid), C.POINTER(ConnectionParameters), P],
            'WlanDisconnect': [W.HANDLE, C.POINTER(Guid), P],
            'WlanRegisterNotification': [W.HANDLE, U32, W.BOOL, P, P, P, C.POINTER(U32)],
        }
        for name, args in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, U32
        self.api.WlanFreeMemory.restype = None
        self.ip.ConvertInterfaceGuidToLuid.argtypes = [C.POINTER(Guid), C.POINTER(C.c_uint64)]
        self.ip.ConvertInterfaceLuidToIndex.argtypes = [C.POINTER(C.c_uint64), C.POINTER(U32)]

    @staticmethod
    def _ok(code, stage):
        if code:
            hint = '；请检查Windows位置访问权限及无线服务' if code == 5 else ''
            raise WifiEnvironmentError(f'{stage}失败（Windows错误码{code}）{hint}')

    def __enter__(self):
        version = U32()
        self._ok(self.api.WlanOpenHandle(2, None, C.byref(version), C.byref(self.handle)), '打开无线服务')
        callback_type = C.WINFUNCTYPE(None, C.POINTER(Notification), C.c_void_p)

        def on_notification(pointer, _context):
            note = pointer.contents
            if note.source == 8 and note.guid.text() == self._scan_guid and note.code in (7, 8):
                self._scan_failed = note.code == 8
                self._scan_event.set()

        self._callback = callback_type(on_notification)
        previous = U32()
        try:
            self._ok(self.api.WlanRegisterNotification(self.handle, 8, False, self._callback,
                                                       None, None, C.byref(previous)), '注册扫描通知')
        except Exception:
            self.api.WlanCloseHandle(self.handle, None)
            raise
        return self

    def __exit__(self, *_args):
        # 注销会等待已在执行的回调完成，之后才释放Python callback。
        previous = U32()
        self.api.WlanRegisterNotification(self.handle, 0, False, None, None, None, C.byref(previous))
        self.api.WlanCloseHandle(self.handle, None)
        self._callback = None

    def select_interface(self, name=''):
        from src.core.wireless_ip import adapters_ipv4
        aliases = {a['guid'].lower(): a['name'] for a in adapters_ipv4()}
        data = C.c_void_p()
        self._ok(self.api.WlanEnumInterfaces(self.handle, None, C.byref(data)), '枚举无线接口')
        interfaces = []
        try:
            count = U32.from_address(data.value).value
            if count > 1024:
                raise WifiEnvironmentError('无线接口列表长度无效')
            for i in range(count):
                item = InterfaceInfo.from_address(data.value + 8 + i * C.sizeof(InterfaceInfo))
                guid = item.guid.text()
                alias = aliases.get(guid.lower(), str(item.description))
                luid, index = C.c_uint64(), U32()
                self._ok(self.ip.ConvertInterfaceGuidToLuid(C.byref(item.guid), C.byref(luid)), '读取接口LUID')
                self._ok(self.ip.ConvertInterfaceLuidToIndex(C.byref(luid), C.byref(index)), '读取接口索引')
                interfaces.append((WifiInterface(guid, alias, index.value), str(item.description)))
        finally:
            self.api.WlanFreeMemory(data)
        exact = [item for item, _ in interfaces if item.name == name] if name else [v[0] for v in interfaces[:1]]
        matches = exact or [item for item, description in interfaces if description == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise WifiEnvironmentError('无线网卡名称匹配多个接口，请选择唯一的接口名称')
        raise WifiEnvironmentError('指定无线网卡不存在或没有可用无线接口')

    def _query(self, interface, opcode):
        data, size = C.c_void_p(), U32()
        guid = Guid.parse(interface.guid)
        code = self.api.WlanQueryInterface(self.handle, C.byref(guid), opcode, None,
                                           C.byref(size), C.byref(data), None)
        return code, data, size.value

    def supported_pairs(self, interface):
        code, data, size = self._query(interface, 9)
        self._ok(code, '读取网卡认证能力')
        try:
            count = U32.from_address(data.value).value
            if count * 8 + 4 > size:
                raise WifiEnvironmentError('网卡认证能力返回无效')
            return tuple(tuple((U32 * 2).from_address(data.value + 4 + 8 * i)) for i in range(count))
        finally:
            self.api.WlanFreeMemory(data)

    def start_scan(self, interface):
        self._scan_guid = interface.guid
        self._scan_event.clear()
        self._scan_failed = False
        guid = Guid.parse(interface.guid)
        self._ok(self.api.WlanScan(self.handle, C.byref(guid), None, None, None), '下发无线扫描')

    def scan_ready(self):
        if self._scan_failed:
            raise WifiEnvironmentError('无线扫描失败')
        return self._scan_event.is_set()

    def observations(self, interface):
        data = C.c_void_p()
        guid = Guid.parse(interface.guid)
        self._ok(self.api.WlanGetNetworkBssList(self.handle, C.byref(guid), None, 1, False,
                                                None, C.byref(data)), '读取无线BSS扫描结果')
        try:
            total, count = (U32 * 2).from_address(data.value)
            entry_size = C.sizeof(BssEntry)
            if total < 8 or 8 + count * entry_size > total:
                raise WifiEnvironmentError('无线BSS列表长度无效')
            observations = []
            for i in range(count):
                address = data.value + 8 + i * entry_size
                item = BssEntry.from_address(address)
                start = address + item.ie_offset
                if item.ie_size and (start < data.value or start + item.ie_size > data.value + total):
                    raise WifiEnvironmentError('无线BSS安全信息长度无效')
                ies = C.string_at(start, item.ie_size) if item.ie_size else b''
                bssid = ':'.join(f'{v:02x}' for v in item.bssid)
                observations.append(WifiObservation(item.ssid.text(), bssid, item.frequency,
                                                     security_pairs(ies, bool(item.capability & 0x10))))
            return observations
        finally:
            self.api.WlanFreeMemory(data)

    def current(self, interface):
        code, data, size = self._query(interface, 7)
        if code == 5023:  # ERROR_INVALID_STATE: disconnected
            return None
        self._ok(code, '读取当前无线连接')
        try:
            if size < C.sizeof(ConnectionAttributes):
                raise WifiEnvironmentError('当前无线连接属性长度无效')
            info = ConnectionAttributes.from_address(data.value)
            if info.state != 1:
                return None
            return WifiConnection(info.association.ssid.text(),
                                  ':'.join(f'{v:02x}' for v in info.association.bssid),
                                  info.security.auth, info.security.cipher)
        finally:
            self.api.WlanFreeMemory(data)

    def connect(self, interface, target, pair):
        name = 'LineCheck-WiFi-' + uuid.uuid4().hex
        xml = profile_xml(name, target, pair)
        bssids = BssidList()
        bssids.header = NdisHeader(0x80, 1, C.sizeof(BssidList))
        bssids.count = bssids.total = 1
        bssids.addresses[0][:] = bytes.fromhex(target.bssid.replace(':', ''))
        # 临时profile模式不会保存/覆盖用户已有profile；断开即清理。
        params = ConnectionParameters(1, xml, None, C.pointer(bssids), 1, 0)
        guid = Guid.parse(interface.guid)
        self._ok(self.api.WlanConnect(self.handle, C.byref(guid), C.byref(params), None),
                 '下发目标BSSID临时连接配置')
        return name

    def disconnect(self, interface):
        guid = Guid.parse(interface.guid)
        self._ok(self.api.WlanDisconnect(self.handle, C.byref(guid), None), '断开临时无线连接')
