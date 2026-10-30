"""一次开关机任务内的 FIFO WiFi 使用权；一次持有覆盖一个通道的双频测试。"""
from collections import deque
from contextlib import contextmanager
import threading
import time
import re


class PowerTestWifiScheduler:
    """仅调度使用权，不操作网卡；取消等待返回 False，不冒充设备失败。"""

    def __init__(self, clock=time.monotonic):
        self._condition = threading.Condition()
        self._pending = deque()
        self._owner = None
        self._clock = clock

    def read_info(self, client, stop_event, emit, solution):
        """沿用原 OpenWrt 四条只读命令；省略原始回显，由调用者记录信息摘要。"""
        if solution != 'openwrt':
            emit('失败：当前方案没有可用的WiFi信息读取实现')
            return None
        values = []
        for path in ('SSID.1.SSID', 'AccessPoint.1.Security.X_SDMC_Key',
                     'SSID.4.SSID', 'AccessPoint.3.Security.X_SDMC_Key'):
            response = client.execute_read_until('bbfdmd -c get Device.WiFi.' + path,
                                                 sensitive=True, stop_event=stop_event,
                                                 on_log=emit)
            match = re.search(r'=>\s*(.*)', response) if isinstance(response, str) else None
            if match is None:
                emit('失败：WiFi信息返回格式无效（回显隐藏）')
                return None
            values.append(match.group(1).strip())
        emit('成功：WiFi信息读取完成')
        return tuple(values)

    def test_bands(self, *, channel, cycle, card, stop_event, emit, connector,
                   wifi_info, test_2g, test_5g, auth, cipher):
        """返回 (success/failed/cancelled/skipped, 频段)，通知由调用者在释放后处理。"""
        label = f"[WiFi测试] 通道{channel} 第{cycle}轮 网卡={card or '自动选择第一张'}"
        if not test_2g and not test_5g:
            emit(f"{label} 跳过：2.4G、5G均未启用")
            return 'skipped', ''
        with self.reserve(channel, cycle, card, stop_event, emit) as acquired:
            if not acquired:
                return 'cancelled', ''
            for band, enabled, offset in (('2.4G', test_2g, 0), ('5G', test_5g, 2)):
                if stop_event.is_set():
                    return 'cancelled', band
                if not enabled:
                    emit(f"{label} 频段={band} 跳过：未启用")
                    continue
                ssid, password = wifi_info[offset:offset + 2]
                prefix = f"{label} 频段={band} SSID={ssid} "
                log = lambda message: emit(prefix + str(message))
                log('开始连接')
                try:
                    ok = connector.connect_wifi(ssid, password, card, psk=auth, cipher=cipher,
                                                stop_event=stop_event, on_log=log)
                except Exception as exc:
                    if stop_event.is_set():
                        log('取消：用户停止')
                        return 'cancelled', band
                    log(f'失败：网卡操作异常（{type(exc).__name__}）')
                    return 'failed', band
                if stop_event.is_set():
                    log('取消：用户停止')
                    return 'cancelled', band
                log('成功：已连接' if ok else '失败：连接尝试已结束')
                if not ok:
                    return 'failed', band
        return 'success', ''

    @contextmanager
    def reserve(self, channel, cycle, card, stop_event, emit):
        ticket = object()
        label = f"[WiFi测试] 通道{channel} 第{cycle}轮 网卡={card or '自动选择第一张'}"
        started = self._clock()
        acquired = False
        queued = False
        try:
            with self._condition:
                self._pending.append(ticket)
                queued = True
                emit(f"{label} 入队；当前占用={self._owner or '无'}")
                last_report = started
                while not stop_event.is_set():
                    if self._owner is None and self._pending[0] is ticket:
                        self._pending.popleft()
                        queued = False
                        self._owner = f"通道{channel} 第{cycle}轮"
                        acquired = True
                        break
                    now = self._clock()
                    if now - last_report >= 10:
                        emit(f"{label} 等待网卡 {now - started:.1f}秒；当前占用={self._owner or '无'}")
                        last_report = now
                    self._condition.wait(0.2)
            # 获得使用权与停止可能同时发生；交接后必须再检查。
            if not acquired or stop_event.is_set():
                emit(f"{label} 取消等待/执行")
                yield False
            else:
                emit(f"{label} 取得使用权；等待 {self._clock() - started:.1f}秒")
                yield True
        finally:
            with self._condition:
                if queued:
                    self._pending.remove(ticket)
                if acquired:
                    self._owner = None
                self._condition.notify_all()
            if acquired:
                emit(f"{label} 释放使用权")
