"""Load and merge project window preferences on the workspace worker."""
from dataclasses import asdict
import json
import re

from src.models.qt_window_placement import DUT_STATUS_FEATURES, WindowPlacement, dut_status_rows
from src.services.project_store import atomic_json


STATE_FILES = {'serial': 'serial.json', 'dut': 'dut.json'}
MODULE_WINDOW_FILE = 'module_windows.json'
MODULE_WINDOW_NAMES = {
    'sample_parameter_writer': '写样机参数',
    'onu_registration': 'ONU 注册',
    'sample_upgrade': '样机升级',
    'test_item_config': '测试项配置',
    'pipeline': '全流程执行',
    'power_test_channel_history': '通道重试历史',
}
LEGACY_GEOMETRY = re.compile(r'(\d{1,6})x(\d{1,6})([+-]\d{1,6})([+-]\d{1,6})')


def _path(context, filename):
    path = context.root / 'ui' / filename
    if path.resolve() != path:
        raise ValueError('窗口状态文件不能重定向到项目目录之外')
    return path


def _read(path):
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    return state if isinstance(state, dict) else {}


def _placement(value, *, positioned):
    if not isinstance(value, dict):
        return None
    width, height = value.get('width'), value.get('height')
    if not all(type(size) is int and 0 < size < 10**6 for size in (width, height)):
        return None
    if not positioned:
        return WindowPlacement(width, height)
    x, y = value.get('x'), value.get('y')
    if not all(type(pos) is int and -10**6 < pos < 10**6 for pos in (x, y)):
        return None
    return WindowPlacement(width, height, x, y)


def _status_heights(values):
    if not isinstance(values, dict):
        return {}
    return {feature: dut_status_rows(values[feature]) for feature in DUT_STATUS_FEATURES if feature in values}


def read_dut_window_state(context):
    try:
        values = _read(_path(context, STATE_FILES['dut']))
    except (OSError, ValueError):
        values = {}
    return dict(placement=_placement(values.get('window_size'), positioned=False),
                status_heights=_status_heights(values.get('current_status_heights')))


def read_window_placement(context, window):
    try:
        state = _read(_path(context, STATE_FILES[window]))
    except (OSError, ValueError):
        return None
    if window == 'dut':
        return _placement(state.get('window_size'), positioned=False)
    saved = _placement(state.get('qt_geometry'), positioned=True)
    if saved is not None:
        return saved
    legacy = state.get('geometry')
    match = LEGACY_GEOMETRY.fullmatch(legacy) if isinstance(legacy, str) else None
    if match is not None:
        width, height, x, y = map(int, match.groups())
        if width >= 1000 and height >= 650:
            return WindowPlacement(width, height, x, y, legacy=True)
    return None


def read_module_window_sizes(context):
    try:
        sizes = _read(_path(context, MODULE_WINDOW_FILE)).get('window_sizes')
    except (OSError, ValueError):
        return {}
    if not isinstance(sizes, dict):
        return {}
    return {key: placement for key in MODULE_WINDOW_NAMES
            if (placement := _placement(sizes.get(key), positioned=False)) is not None}


def save_window_placement(context, window, placement=None, *, status_heights=None):
    filename = MODULE_WINDOW_FILE if window in MODULE_WINDOW_NAMES else STATE_FILES[window]
    path = _path(context, filename)
    try:
        state = _read(path)
    except (UnicodeError, json.JSONDecodeError):
        state = {}
    if placement is not None:
        value = asdict(placement)
        if _placement(value, positioned=window == 'serial') is None:
            raise ValueError('窗口尺寸或位置无效')
        if window == 'serial':
            state['qt_geometry'] = {key: value[key] for key in ('width', 'height', 'x', 'y')}
        elif window in MODULE_WINDOW_NAMES:
            previous = state.get('window_sizes')
            sizes = dict(previous) if isinstance(previous, dict) else {}
            sizes[window] = {key: value[key] for key in ('width', 'height')}
            state['window_sizes'] = sizes
        else:
            state['window_size'] = {key: value[key] for key in ('width', 'height')}
    if window == 'dut' and status_heights is not None:
        previous = state.get('current_status_heights')
        values = _status_heights(status_heights)
        state['current_status_heights'] = dict(previous, **values) if isinstance(previous, dict) else values
    atomic_json(path, state)
