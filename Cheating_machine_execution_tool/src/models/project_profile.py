"""Versioned project intent and DUT identities. No transport or resource allocation."""
from uuid import UUID, uuid4


TEST_TYPES = {'power_cycle': '自动开关机', 'service_aging': '全业务老化'}
OPTIONAL_STEPS = ('parameters', 'wan', 'voice', 'tr069')
COLLECTOR_LABELS = {
    'wifi_2g': '2.4G WiFi', 'wifi_5g': '5G WiFi', 'iptv': 'IPTV 视频', 'voice': 'VOICE 连续通话',
    'tr069': 'TR069 注册', 'lan_ping': 'LAN Ping', 'keys_led': '按键 / LED', 'easymesh': 'EasyMesh',
    'wifi_sta_video': 'WiFi STA 视频', 'wifi_reconnect': 'WiFi 反复连接', 'serial_log': '串口日志',
    'dut_presence': 'DUT 在线与启动状态', 'cpu_memory': 'CPU / 内存',
}
COLLECTORS = tuple(k for k in COLLECTOR_LABELS if k != 'cpu_memory')
FEED_COLLECTORS = tuple(k for k in COLLECTORS if k != 'lan_ping')
DUT_FIELDS = ('label', 'hardware_id', 'target_firmware', 'serial_port', 'network_adapter',
              'vlan', 'power_channel', 'other_devices')


def _adb_serial(value):
    if not isinstance(value, str) or (value and not value.isprintable()):
        raise ValueError('ADB 设备标识须为可显示的文本')
    return value.strip()


def adb_resource_key(serial):
    """Encode original-case identity for the host's case-folded physical key namespace."""
    value = _adb_serial(serial)
    return 'adb:' + value.encode('utf-8').hex() if value else ''


def adb_serial_from_key(key):
    if not isinstance(key, str) or not key.startswith('adb:'):
        return None
    try:
        serial = bytes.fromhex(key[4:]).decode('utf-8')
        return serial if serial and adb_resource_key(serial) == key else None
    except ValueError:
        return None


def dut_resource_keys(duts, channels=None):
    selected = None if channels is None else set(channels)
    keys = set()
    for dut in duts:
        if selected is not None and dut.get('channel') not in selected:
            continue
        keys.add('dut:record:' + str(UUID(dut['dut_id'])))
        hardware_id = dut.get('hardware_id', '').strip().casefold()
        if hardware_id:
            keys.add('dut:hardware:' + hardware_id)
        adb = adb_resource_key(dut.get('adb_serial', ''))
        if adb:
            keys.add(adb)
    return tuple(sorted(keys))


def _fields(value, allowed, title):
    if not isinstance(value, dict) or value.keys() - set(allowed):
        raise ValueError(f'{title}字段不受支持')


def _text(value, title):
    if not isinstance(value, str) or '\0' in value:
        raise ValueError(f'{title}须为文本')
    return value.strip()


def _number(value, title, maximum=None):
    if value is not None and (type(value) is not int or value < 1 or (maximum is not None and value > maximum)):
        raise ValueError(f'{title}须为正整数' if maximum is None else f'{title}须在 1–{maximum} 范围内')
    return value


def _selection(values, allowed, title):
    if not isinstance(values, list) or any(not isinstance(val, str) or val not in allowed for val in values):
        raise ValueError(f'{title}含不支持的选项')
    return [key for key in allowed if key in values]


def normalize_project_profile(value, *, assign_ids=True):
    """Return an owned JSON dictionary. Generate IDs only when accepting new input."""
    _fields(value, ('schema_version', 'test_type', 'model', 'software_version', 'requirements',
                    'optional_steps', 'type_config', 'duts'), '项目档案')
    version = value.get('schema_version', 1)
    if type(version) is not int or version != 1:
        raise ValueError('项目档案版本不受支持')
    kind = value.get('test_type')
    if not isinstance(kind, str) or kind not in TEST_TYPES:
        raise ValueError('请选择自动开关机或全业务老化')
    settings = value.get('type_config', {})
    if kind == 'power_cycle':
        _fields(settings, ('target_cycles',), '开关机计划')
        settings = {'target_cycles': _number(settings.get('target_cycles'), '目标轮数')}
    else:
        _fields(settings, ('target_hours', 'collectors', 'feed_collectors'), '老化计划')
        collectors = _selection(settings.get('collectors', []), COLLECTORS, '采集项')
        feeds = _selection(settings.get('feed_collectors', []), FEED_COLLECTORS, '现场采集来源')
        if not set(feeds).issubset(collectors):
            raise ValueError('现场采集来源必须属于已选择的监测业务')
        if 'dut_presence' in collectors and 'dut_presence' not in feeds:
            raise ValueError('DUT 在线与启动状态需要现场采集来源')
        settings = {'target_hours': _number(settings.get('target_hours'), '目标时长'),
                    'collectors': collectors}
        if feeds:
            settings['feed_collectors'] = feeds
    rows = value.get('duts', [])
    if not isinstance(rows, list):
        raise ValueError('DUT 列表格式无效')
    duts, identities, channels = [], set(), set()
    for row in rows:
        _fields(row, (*DUT_FIELDS, 'dut_id', 'channel', 'adb_serial'), 'DUT')
        data = {key: _text(row.get(key, ''), f'DUT {key}') for key in DUT_FIELDS}
        adb = _adb_serial(row.get('adb_serial', ''))
        if adb:
            data['adb_serial'] = adb
        if not data['label']:
            raise ValueError('请填写每台 DUT 的名称')
        identifier = row.get('dut_id', '')
        if (identifier is None or identifier == '') and assign_ids:
            identifier = str(uuid4())
        try:
            identifier = str(UUID(identifier))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('DUT 身份须为有效 UUID') from None
        channel = _number(row.get('channel'), 'DUT 通道', 16)
        if identifier in identities or (channel is not None and channel in channels):
            raise ValueError('DUT 身份或通道重复')
        identities.add(identifier)
        channels.add(channel)
        duts.append(dict(data, dut_id=identifier, channel=channel))
    return dict(schema_version=1, test_type=kind, model=_text(value.get('model', ''), '型号'),
                software_version=_text(value.get('software_version', ''), '软件版本'),
                requirements=_text(value.get('requirements', ''), '项目要求'),
                optional_steps=_selection(value.get('optional_steps', []), OPTIONAL_STEPS, '选做准备步骤'),
                type_config=settings, duts=duts)
