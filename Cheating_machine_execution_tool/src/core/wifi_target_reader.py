"""通过现有锁源 Telnet 只读解析 bbfdmd WiFi Mapping 和目标身份。"""
import json
import re

from src.models.wifi_test_models import (
    WifiBandTarget, WifiSnapshot, WifiEnvironmentError, check_stop, normalize_bssid,
)


def read_wifi_snapshot(client, stop, emit, *, bands=('2.4G', '5G'), allow_partial=False):
    def read(path):
        check_stop(stop)
        emit('下发只读命令：bbfdmd -c get ' + path)
        response = client.execute_read_until('bbfdmd -c get ' + path, sensitive=True,
                                             stop_event=stop, on_log=emit)
        check_stop(stop)
        return response if isinstance(response, str) else ''

    def scalar(path):
        response = read(path)
        matches = re.findall(r'=>[^\S\r\n]*([^\r\n]*)', response)
        if len(matches) != 1:
            raise WifiEnvironmentError('WiFi字段缺失或返回格式无效：' + path)
        value = matches[0].strip()
        try:
            decoded = json.loads(value)
            return str(decoded) if not isinstance(decoded, str) else decoded
        except (ValueError, TypeError):
            return value

    dual = None
    try:
        value = scalar('Device.WiFi.X_SDMC_DualBandEnable').split(',')[0].lower()
        dual = {'1': True, 'true': True, '0': False, 'false': False}.get(value)
    except WifiEnvironmentError:
        emit('双频合一状态未知；不会根据SSID同名推断')

    node_cache = {}

    def instance(node, token):
        if not token.isdigit() or int(token) <= 0:
            raise WifiEnvironmentError('WiFi Mapping索引无效')
        if node not in node_cache:
            response = read('Device.WiFi.' + node + '.')
            node_cache[node] = re.findall(
                r'Device\.WiFi\.' + node + r'\.(\d+)\.X_SDMC_Instance\s*=>\s*["\']?(\d+)', response)
        nodes = node_cache[node]
        if 1 <= int(token) <= len(nodes):
            return nodes[int(token) - 1][1]
        if any(v == token for _, v in nodes):
            return token
        raise WifiEnvironmentError('无法可靠解析WiFi ' + node + ' Mapping')

    targets = []
    for band in bands:
        try:
            mapping = scalar('Device.WiFi.X_SDMC_Mapping_' + ('2G' if band == '2.4G' else '5G'))
            tokens = [v.strip() for v in mapping.split('@')[0].split(',')]
            if len(tokens) != 3:
                raise WifiEnvironmentError('WiFi Mapping格式无效')
            radio, ap, ssid_index = (instance(n, t) for n, t in
                                     zip(('Radio', 'AccessPoint', 'SSID'), tokens))
            ssid_path = 'Device.WiFi.SSID.' + ssid_index + '.'
            security_path = 'Device.WiFi.AccessPoint.' + ap + '.Security.'
            enabled = scalar(ssid_path + 'Enable').lower()
            if enabled not in ('1', 'true'):
                raise WifiEnvironmentError(band + ' WiFi未启用')
            ssid = scalar(ssid_path + 'SSID')
            bssid = normalize_bssid(scalar(ssid_path + 'BSSID'))
            security = scalar(security_path + 'ModeEnabled')
            password = '' if security.lower() in ('none', 'open') else scalar(security_path + 'X_SDMC_Key')
            if not ssid or len(ssid.encode('utf-8')) > 32:
                raise WifiEnvironmentError('目标SSID为空或超过32字节')
            targets.append(WifiBandTarget(band, ssid, bssid, password, security))
            emit(f'目标已读取：频段={band} Radio={radio} SSID={ssid} BSSID={bssid} 认证={security}')
        except WifiEnvironmentError as exc:
            if not allow_partial:
                raise
            emit(f'{band}目标信息不可用：{exc}')
    if not targets:
        raise WifiEnvironmentError('没有可可靠识别的样机WiFi目标')
    if len({t.bssid for t in targets}) != len(targets):
        raise WifiEnvironmentError('两个频段返回相同BSSID，无法区分目标')
    emit('双频合一状态=' + ('未知' if dual is None else ('开启' if dual else '关闭')))
    return WifiSnapshot(tuple(targets), dual)
