"""正式 WiFi 的连接、稳定核验和可选无线Ping；由外层FIFO持有使用权。"""
import time

from src.core.windows_wifi import NativeWifiBackend, choose_security, AUTH_NAMES, CIPHER_NAMES
from src.core.wireless_ping import run_wireless_ping
from src.core.wireless_ip import validate_ping_target
from src.models.wifi_test_models import (
    WifiEnvironmentError, WifiVerificationError, WifiScanError, WifiCancelled,
    frequency_band, check_stop, wait,
)


def validate_wifi_options(options, enabled=True, solution='openwrt'):
    if not enabled:
        return
    if options.connection_test_mode not in ('per_band', 'unified'):
        raise ValueError('WiFi连接测试模式无效')
    if options.security_source not in ('auto', 'manual'):
        raise ValueError('WiFi认证来源无效')
    if solution != 'openwrt':
        raise ValueError('当前ONU方案暂不支持WiFi信息读取，仅支持openwrt')
    if options.wireless_ping_enable:
        validate_ping_target(options.wireless_ping_target)


class WifiConnectionService:
    def __init__(self, backend_factory=NativeWifiBackend, ping=run_wireless_ping, clock=time.monotonic):
        self.backend_factory = backend_factory
        self.ping = ping
        self.clock = clock

    def run(self, snapshot, options, card, test_2g, test_5g, auth, cipher, stop, emit):
        band_label = ''
        try:
            check_stop(stop)
            with self.backend_factory() as backend:
                interface = backend.select_interface(card)
                emit(f'实际无线网卡={interface.name} GUID={interface.guid} ifIndex={interface.index}')
                supported = backend.supported_pairs(interface)
                if options.connection_test_mode == 'unified':
                    groups = [('合一网络', snapshot.targets)]
                else:
                    groups = [(band, tuple(t for t in snapshot.targets if t.band == band))
                              for band, enabled in (('2.4G', test_2g), ('5G', test_5g)) if enabled]
                for band_label, targets in groups:
                    if not targets:
                        raise WifiEnvironmentError(band_label + '没有可可靠识别的目标')
                    log = lambda message: emit(f'频段={band_label} {message}')
                    ok = self._test_group(backend, interface, targets, options, auth, cipher,
                                          stop, log, supported)
                    if not ok:
                        return 'failed', band_label
                    check_stop(stop)
                    log('成功：本项无线测试通过')  # _test_group的finally已确认清理完成。
                check_stop(stop)
                return 'success', ''
        except WifiCancelled:
            emit('取消：用户停止WiFi测试')
            return 'cancelled', band_label
        except (WifiEnvironmentError, ValueError) as exc:
            if stop.is_set():
                emit('取消：用户停止WiFi测试')
                return 'cancelled', band_label
            emit(f'测试环境异常：{exc}')
            return 'error', f'{band_label}：{exc}'
        except WifiVerificationError as exc:
            if stop.is_set():
                emit('取消：用户停止WiFi测试')
                return 'cancelled', band_label
            emit(f'验证失败：{exc}')
            return 'failed', f'{band_label}：{exc}'
        except Exception as exc:
            if stop.is_set():
                return 'cancelled', band_label
            # 驱动异常可能携带XML/密钥；禁止打印异常原文。
            emit(f'测试环境异常：无线接口调用异常（{type(exc).__name__}）')
            return 'error', f'{band_label}：无线接口调用异常（{type(exc).__name__}）'

    def _guard(self, backend, interface, targets, pair, options, stop=None):
        if stop is not None:
            check_stop(stop)
        connection = backend.current(interface)
        if stop is not None:
            check_stop(stop)
        if connection is None:
            raise WifiVerificationError('目标无线连接已断开')
        target = next((t for t in targets if t.bssid == connection.bssid and t.ssid == connection.ssid), None)
        if target is None:
            raise WifiVerificationError('实际SSID/BSSID不属于本项目标样机或目标频段')
        observations = backend.observations(interface)
        if stop is not None:
            check_stop(stop)
        observation = next((v for v in observations if v.bssid == connection.bssid and v.ssid == connection.ssid), None)
        if observation is None:
            raise WifiVerificationError('无法核验实际连接频率')
        if frequency_band(observation.frequency) != target.band:
            raise WifiVerificationError('实际连接频段与样机目标不符')
        if (connection.auth, connection.cipher) != pair:
            raise WifiVerificationError('实际认证/加密与本次连接约束不符')
        return connection, observation

    def _wait_disconnected(self, backend, interface, stop):
        deadline, stable_since = self.clock() + 5, None
        while True:
            check_stop(stop)
            now = self.clock()
            if backend.interface_state(interface) == 4:  # wlan_interface_state_disconnected
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= 0.5:
                    return
            else:
                stable_since = None
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise WifiEnvironmentError('临时连接断开未确认（最长5秒，要求连续断开至少0.5秒）')
            wait(min(0.2, remaining), stop, clock=self.clock)

    def _test_group(self, backend, interface, targets, options, auth, cipher, stop, emit, supported):
        for attempt in range(1, 5):
            check_stop(stop)
            deadline = self.clock() + 20
            owned = False
            stable_since = None
            ping_phase = False
            emit(f'第 {attempt}/4 次连接，扫描/连接/核验共约20秒；认证来源={options.security_source}')
            try:
                emit('下发无线扫描')
                try:
                    check_stop(stop)
                    backend.start_scan(interface)
                    while True:
                        check_stop(stop)
                        if backend.scan_ready():
                            break
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            raise WifiScanError('扫描超时', retryable=True,
                                                reason='20秒扫描/连接/核验预算已用尽')
                        wait(min(0.2, remaining), stop, clock=self.clock)
                finally:
                    backend.end_scan()
                check_stop(stop)
                if self.clock() >= deadline:
                    raise WifiScanError('扫描超时', retryable=True,
                                        reason='20秒扫描/连接/核验预算已用尽')
                observations = backend.observations(interface)
                candidates = [(t, o) for t in targets for o in observations
                              if t.bssid == o.bssid and t.ssid == o.ssid and frequency_band(o.frequency) == t.band]
                if not candidates:
                    raise WifiVerificationError('扫描未发现目标BSSID或频段不符')
                chosen = None
                for target, observation in candidates:
                    try:
                        pair = choose_security(observation, supported, options.security_source, auth, cipher)
                    except WifiEnvironmentError:
                        continue
                    chosen = target, pair
                    break
                if chosen is None:
                    raise WifiEnvironmentError('目标网络、网卡能力与认证约束没有受支持的组合')
                target, pair = chosen
                emit(f'目标SSID={target.ssid} BSSID={target.bssid} 频段={target.band} '
                     f'认证={AUTH_NAMES.get(pair[0], pair[0])} 加密={CIPHER_NAMES.get(pair[1], pair[1])}')
                check_stop(stop)
                if self.clock() >= deadline:
                    raise WifiVerificationError('扫描/连接/核验预算已用尽，未下发连接')
                owned = True  # 调用即可能改变接口，异常时也必须清理临时连接。
                emit('下发目标BSSID临时连接配置（不保存或覆盖用户配置）')
                backend.connect(interface, target, pair)
                stable_since = None
                last_failure = '未连接目标网络'
                while self.clock() < deadline:
                    check_stop(stop)
                    try:
                        current, observed = self._guard(backend, interface, targets, pair, options, stop)
                    except WifiVerificationError as exc:
                        stable_since = None
                        last_failure = str(exc)
                    else:
                        if stable_since is None:
                            stable_since = self.clock()
                        if self.clock() - stable_since >= 2:
                            emit(f'连接核验成功：SSID={current.ssid} BSSID={current.bssid} '
                                 f'实际频段={frequency_band(observed.frequency)} '
                                 f'认证={AUTH_NAMES.get(current.auth, current.auth)} '
                                 f'加密={CIPHER_NAMES.get(current.cipher, current.cipher)}')
                            guard = lambda: self._guard(backend, interface, targets, pair, options, stop)
                            if options.wireless_ping_enable:
                                ping_phase = True
                                result = self.ping(interface, options.wireless_ping_target, stop, emit, guard)
                                check_stop(stop)
                                guard()
                                if not result.ok:
                                    raise WifiVerificationError('无线Ping全部无有效回复，不重连或重跑整组Ping')
                            else:
                                emit('跳过：无线Ping未启用')
                            check_stop(stop)
                            return True
                    wait(min(0.2, max(0, deadline - self.clock())), stop, clock=self.clock)
                raise WifiVerificationError(last_failure + '，连接/稳定核验超时')
            except WifiScanError as exc:
                check_stop(stop)
                if ping_phase:
                    raise
                if not exc.retryable or attempt == 4:
                    action = '立即结束' if not exc.retryable else '次数已用尽，结束当前频段'
                    raise WifiEnvironmentError(f'第{attempt}/4次扫描失败：{exc}；{action}') from None
                emit(f'第{attempt}/4次扫描失败：{exc}；10秒后重试')
            except WifiVerificationError as exc:
                if ping_phase:
                    # Ping阶段离开目标/换频段，不能通过重新关联掩盖。
                    raise
                emit(f'第 {attempt}/4 次未通过：{exc}')
            finally:
                if owned:
                    emit('下发断开临时连接；不删除电脑原有无线配置')
                    try:
                        backend.disconnect(interface)
                    except Exception:
                        if not stop.is_set():
                            raise WifiEnvironmentError('临时无线连接清理失败，请检查所选网卡') from None
                        emit('取消后临时连接清理异常，请检查所选网卡')
                    else:
                        if stop.is_set():
                            emit('取消：已下发临时连接断开，断开状态未确认')
                        else:
                            try:
                                self._wait_disconnected(backend, interface, stop)
                            except WifiCancelled:
                                emit('取消：已下发临时连接断开，断开状态未确认')
                                raise
                            except WifiEnvironmentError as exc:
                                raise WifiEnvironmentError(f'临时连接断开未确认：{exc}') from None
                            emit('临时连接已清理')
            if attempt < 4:
                emit('等待10秒后重试')
                wait(10, stop, clock=self.clock)
        emit('失败：第4/4次连接仍未通过')
        return False
