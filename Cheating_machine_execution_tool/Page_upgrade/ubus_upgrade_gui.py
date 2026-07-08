#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UBUS 升级工具 — PyQt5 图形界面（支持 1-8 工位并行升级）
"""

import sys
import os
import socket
import threading

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QGroupBox, QScrollArea, QFrame, QMessageBox
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont

from ubus_upgrade import SdmcUbusLibBase

# ---- 线程局部存储，用于多线程日志分流 ----
_thread_local = threading.local()


def get_local_ips():
    """
    获取本机所有有效非回环 IPv4 地址列表。
    优先通过主机名解析获取（避免 DNS 超时阻塞），失败则通过 UDP 连接探测。
    """
    ips = set()

    # 方法1: 通过主机名解析获取所有 IP（快速、不会阻塞）
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    # 方法2: UDP 连接探测获取首选本地 IP（兜底）
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.0)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                ips.add(ip)
        except Exception:
            pass

    return sorted(ips)


# ============================================================
#  线程安全日志流（通过 threading.local 实现多线程 print 分流）
# ============================================================

class ThreadLogStream:
    """单个线程的日志缓冲流，通过 Qt 信号发送到 GUI"""

    def __init__(self, signal):
        self._signal = signal
        self._buffer = ""

    def write(self, text):
        if not text:
            return
        self._buffer += text
        while "\n" in self._buffer:
            idx = self._buffer.index("\n")
            line = self._buffer[:idx].rstrip("\r")
            self._buffer = self._buffer[idx + 1:]
            if line:
                self._signal.emit(line)

    def flush(self):
        if self._buffer:
            self._signal.emit(self._buffer.rstrip("\r"))
            self._buffer = ""


class DispatchStream:
    """
    全局标准输出代理。
    每次 write 时从线程局部存储取出当前线程的 ThreadLogStream，
    实现多线程 print 互不串扰。
    """

    def write(self, text):
        stream = getattr(_thread_local, "log_stream", None)
        if stream is not None:
            stream.write(text)

    def flush(self):
        stream = getattr(_thread_local, "log_stream", None)
        if stream is not None:
            stream.flush()


# ============================================================
#  后台升级线程
# ============================================================

class UpgradeThread(QThread):
    """单个工位的升级任务线程"""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(int, bool)  # station_id, success

    def __init__(self, station_id, bind_ip, device_ip, username, password, file_path):
        super().__init__()
        self._station_id = station_id
        self._bind_ip = bind_ip
        self._device_ip = device_ip
        self._username = username
        self._password = password
        self._file_path = file_path

    def run(self):
        stream = ThreadLogStream(self.log_signal)
        _thread_local.log_stream = stream

        try:
            lib = SdmcUbusLibBase(self._bind_ip if self._bind_ip else None)
            result = lib.upgrade_main(
                self._device_ip,
                self._username,
                self._password,
                self._file_path,
            )
            self.finished_signal.emit(self._station_id, result)
        except Exception as e:
            self.log_signal.emit(f"工位{self._station_id} 升级异常: {e}")
            self.finished_signal.emit(self._station_id, False)
        finally:
            _thread_local.log_stream = None


# ============================================================
#  主窗口
# ============================================================

class UpgradeWindow(QMainWindow):
    """主窗口 —— 支持 1-8 工位"""

    MAX_STATIONS = 8

    def __init__(self):
        super().__init__()
        self._threads = []          # 当前运行中的 UpgradeThread 列表
        self._completed_count = 0   # 已完成线程计数
        self._local_ips = get_local_ips()

        self.setWindowTitle("UBUS 升级工具")
        self.setMinimumSize(900, 550)
        self.resize(900, 680)  # 默认尺寸：4 工位无需滚动
        self._init_ui()

    # ===================== UI 构建 =====================

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ---- 工位数选择 ----
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("工位数:"))
        self.cmb_station_count = QComboBox()
        self.cmb_station_count.addItems([str(i) for i in range(1, self.MAX_STATIONS + 1)])
        self.cmb_station_count.currentIndexChanged.connect(self._on_station_count_changed)
        top_row.addWidget(self.cmb_station_count)
        top_row.addStretch()
        root.addLayout(top_row)

        # ---- 工位参数区（可滚动） ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        self._stations_layout = QVBoxLayout(scroll_content)
        self._stations_layout.setSpacing(6)
        self._stations_layout.setContentsMargins(0, 0, 0, 0)

        # 预创建 8 个工位 GroupBox
        self._station_groups = []
        self._station_widgets = []  # list of dict: {cmb_ip, txt_ip, txt_user, txt_pass}
        for i in range(1, self.MAX_STATIONS + 1):
            group, widgets = self._create_station_group(i)
            self._station_groups.append(group)
            self._station_widgets.append(widgets)
            self._stations_layout.addWidget(group)

        self._stations_layout.addStretch()
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        # ---- 公共参数：升级文件 ----
        file_group = QGroupBox("公共参数")
        file_layout = QHBoxLayout(file_group)
        file_layout.addWidget(QLabel("升级文件:"))
        self.txt_file_path = QLineEdit()
        self.txt_file_path.setPlaceholderText("选择固件文件（所有工位共用）...")
        file_layout.addWidget(self.txt_file_path, stretch=1)
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(btn_browse)
        root.addWidget(file_group)

        # ---- 开始按钮 ----
        self.btn_start = QPushButton("开始升级")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setStyleSheet(
            "QPushButton {"
            "  font-size: 14px; font-weight: bold;"
            "  background-color: #0078D4; color: white;"
            "  border: none; border-radius: 4px;"
            "}"
            "QPushButton:hover  { background-color: #106EBE; }"
            "QPushButton:disabled { background-color: #CCCCCC; }"
        )
        self.btn_start.clicked.connect(self._on_start_upgrade)
        root.addWidget(self.btn_start)

        # ---- 日志输出区 ----
        root.addWidget(QLabel("日志输出:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "QTextEdit { background-color: #1E1E1E; color: #D4D4D4; }"
        )
        root.addWidget(self.log_area, stretch=2)

        # 默认显示 1 个工位
        self._on_station_count_changed(0)

    def _create_station_group(self, index):
        """创建一个工位的控件组（单行紧凑布局），返回 (QGroupBox, widget_dict)"""
        group = QGroupBox(f"工位 {index}")
        row = QHBoxLayout(group)
        row.setSpacing(8)
        row.setContentsMargins(8, 4, 8, 4)

        # 绑定 IP
        row.addWidget(QLabel("绑定 IP:"))
        cmb_ip = QComboBox()
        cmb_ip.addItems(self._local_ips)
        if self._local_ips:
            cmb_ip.setCurrentIndex(0)
        cmb_ip.setMinimumWidth(130)
        row.addWidget(cmb_ip)

        row.addSpacing(12)

        # 样机 IP
        row.addWidget(QLabel("样机 IP:"))
        txt_ip = QLineEdit("192.168.29.1")
        txt_ip.setMinimumWidth(110)
        row.addWidget(txt_ip)

        row.addSpacing(12)

        # 账号
        row.addWidget(QLabel("账号:"))
        txt_user = QLineEdit("sdmc")
        txt_user.setMaximumWidth(90)
        row.addWidget(txt_user)

        row.addSpacing(12)

        # 密码
        row.addWidget(QLabel("密码:"))
        txt_pass = QLineEdit("1234")
        txt_pass.setEchoMode(QLineEdit.Password)
        txt_pass.setMaximumWidth(100)
        row.addWidget(txt_pass)

        row.addStretch()

        widgets = {
            "cmb_ip": cmb_ip,
            "txt_ip": txt_ip,
            "txt_user": txt_user,
            "txt_pass": txt_pass,
        }
        return group, widgets

    # ===================== 事件处理 =====================

    def _on_station_count_changed(self, index):
        """工位数下拉切换时，显示/隐藏对应数量的工位"""
        count = index + 1
        for i, group in enumerate(self._station_groups):
            group.setVisible(i < count)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择固件文件",
            "",
            "固件文件 (*.bin *.pkgtb *.img);;所有文件 (*.*)",
        )
        if path:
            self.txt_file_path.setText(path)

    def _on_start_upgrade(self):
        """开始升级：收集可见工位参数，为每个工位启动一个线程"""
        file_path = self.txt_file_path.text().strip()

        # 校验证书文件
        if not file_path:
            QMessageBox.warning(self, "参数不完整", "请选择升级文件。")
            return
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "文件不存在", f"升级文件不存在:\n{file_path}")
            return

        # 收集可见工位的参数
        count = self.cmb_station_count.currentIndex() + 1
        stations = []
        for i in range(count):
            w = self._station_widgets[i]
            bind_ip = w["cmb_ip"].currentText().strip()
            device_ip = w["txt_ip"].text().strip()
            username = w["txt_user"].text().strip()
            password = w["txt_pass"].text().strip()

            if not all([device_ip, username, password]):
                QMessageBox.warning(
                    self, "参数不完整",
                    f"工位 {i + 1} 参数不完整，请填写样机 IP / 账号 / 密码。"
                )
                return

            stations.append({
                "id": i + 1,
                "bind_ip": bind_ip,
                "device_ip": device_ip,
                "username": username,
                "password": password,
            })

        # 禁用按钮，清日志
        self.btn_start.setEnabled(False)
        self.btn_start.setText("升级中...")
        self.log_area.clear()
        sys.stdout = DispatchStream()  # 全局仅替换一次

        self._log("=" * 60)
        self._log(f"共 {len(stations)} 个工位，启动并行升级")
        for s in stations:
            self._log(
                f"  工位{s['id']}: bind={s['bind_ip']}, "
                f"ip={s['device_ip']}, user={s['username']}"
            )
        self._log(f"  升级文件: {file_path}")
        self._log("=" * 60)

        # 启动线程
        self._threads = []
        self._completed_count = 0
        for s in stations:
            t = UpgradeThread(
                station_id=s["id"],
                bind_ip=s["bind_ip"],
                device_ip=s["device_ip"],
                username=s["username"],
                password=s["password"],
                file_path=file_path,
            )
            t.log_signal.connect(self._log)
            t.finished_signal.connect(self._on_thread_finished)
            self._threads.append(t)
            t.start()

    def _log(self, message):
        self.log_area.append(message)
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_thread_finished(self, station_id, success):
        """单个工位线程完成时的回调"""
        self._completed_count += 1
        status = "✓ 成功" if success else "✗ 失败"
        self._log(f"[工位{station_id}] 升级结束 — {status} ({self._completed_count}/{len(self._threads)})")

        if self._completed_count >= len(self._threads):
            # 全部完成
            self.btn_start.setEnabled(True)
            self.btn_start.setText("开始升级")
            sys.stdout = sys.__stdout__
            self._log("=" * 60)
            self._log("全部工位升级结束。")
            QMessageBox.information(
                self, "升级结束",
                f"共 {len(self._threads)} 个工位，全部执行完毕。\n详见日志。"
            )


def main():
    app = QApplication(sys.argv)
    window = UpgradeWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
