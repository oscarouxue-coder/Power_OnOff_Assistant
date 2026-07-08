# -*- coding: utf-8 -*-
"""
串口自动升级工具
通过串口连接设备，自动发送升级指令完成固件升级。
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import csv
try:
    import openpyxl  # 用于读取 .xlsx / .xlsm
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
import os
import subprocess
import threading
import time
from tkinter import filedialog
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 硬编码指令列表（原 指令.txt 内容）
HARDCODED_COMMANDS = [
    "cd /mnt/defaults",
    "mount -t ubifs -o remount,rw ubi:defaults /mnt/defaults",
    "rm -rf sdmc_pp",
    "cp sdmc_linux_pp sdmc_pp",
    "cd //mnt/defaults/wl",
    "rm nvram.nvm",
    "cd /data/",
    "rm .kernel_nvram.setting .user_nvram.setting",
    "firstboot -y,reboot,",
]

# 写参工具 Tab 默认行（标签, 写参指令）。共 15 条。
DEFAULT_PARAM_ROWS = [
    ("SN",              "ppctl set SERIAL_NUMBER="),
    ("XPON SN",          "ppctl set XPON_SN="),
    ("MAC",              "ppctl set LAN_BASE_MAC_ADDRESS="),
    ("2.4主SSID",        "ppctl set WIFI_SSID_24G1="),
    ("2.4主SSID密码",    "ppctl set WIFI_KEY_24G1="),
    ("5G主SSID",         "ppctl set WIFI_SSID_5G1="),
    ("5G主SSID密码",     "ppctl set WIFI_KEY_5G1="),
    ("2.4G国家码",       "ppctl set WIFI_CCODE_24G="),
    ("5G国家码",         "ppctl set WIFI_CCODE_5G="),
    ("产品名",           "ppctl set PRODUCT_CLASS="),
    ("super用户账号",     "ppctl set SUPER_USERNAME="),
    ("super用户密码",     "ppctl set SUPER_PASSWORD="),
    ("普通用户账号",       "ppctl set USER_USERNAME="),
    ("普通用户密码",       "ppctl set USER_PASSWORD="),
    ("IP地址",           "ppctl set LAN_IP_ADDRESS="),
]

# 写参标签 → 参数表格表头的列名（大小写不敏感匹配）。MAC 走特殊值。
PARAM_HEADER_MAP = {
    "SN":              "SN",
    "XPON SN":         "GPON SN",
    "MAC":             "__SELECTED_MAC__",
    "2.4主SSID":        "2.4G SSID",
    "2.4主SSID密码":    "WiFi Password",
    "5G主SSID":         "5G SSID",
    "5G主SSID密码":     "WiFi Password",
    "2.4G国家码":       "Country code",
    "5G国家码":         "Country code",
    "产品名":           "Product Class",
    "super用户账号":    "Superuser Name",
    "super用户密码":    "Superuser Password",
    "普通用户账号":     "User Name",
    "普通用户密码":     "Password",
    "IP地址":           "IP",
}

# 写参流程二次登录（设备进入工厂模式后）使用的固定账号密码
FACTORY_ACCOUNT = "root"
FACTORY_PASSWORD = "t*hEQ#BHu7z%3n"

# 串口默认参数
DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 0.5


class SerialUpgradeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("串口自动升级工具")
        self.root.resizable(True, True)
        self.root.geometry("800x720")

        self.serial_conn = None
        self.upgrading = False
        self.writing_params = False

        self._build_ui()
        self._refresh_ports()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        """构建 UI：
        ┌─ 顶部公共区（串口参数 + 账号密码 + 状态/进度 + 停止）─ 任何 Tab 可见
        ├─ 中部 Tab Notebook（升级 vs 写参）                        ─ Tab 私有
        └─ 底部公共区（执行日志）                                 ─ 任何 Tab 可见
        """
        # 1. 顶部公共
        self._build_common_top(self.root)

        # 2. 中部 Tab
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.upgrade_tab = ttk.Frame(notebook, padding="10")
        notebook.add(self.upgrade_tab, text="串口升级")
        self._build_upgrade_ui(self.upgrade_tab)

        self.param_tab = ttk.Frame(notebook, padding="10")
        notebook.add(self.param_tab, text="写参工具")
        self._build_param_ui(self.param_tab)

        # 3. 底部公共
        self._build_common_bottom(self.root)

        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_common_top(self, parent):
        """顶部公共区：串口参数 + 账号密码 + 状态 + 停止按钮 + 进度条。
        任何 Tab 都看得到。
        """
        main_frame = ttk.Frame(parent, padding="10")
        main_frame.pack(fill=tk.X)

        # 第 0 行：串口参数
        row0 = ttk.Frame(main_frame)
        row0.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(row0, text="COM 端口:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            row0, textvariable=self.port_var, state="readonly", width=18
        )
        self.port_combo.pack(side=tk.LEFT, padx=(5, 10))
        self.refresh_btn = ttk.Button(
            row0, text="刷新", width=6, command=self._refresh_ports
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(row0, text="波特率:").pack(side=tk.LEFT)
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUDRATE))
        baud_combo = ttk.Combobox(
            row0,
            textvariable=self.baud_var,
            values=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"],
            width=10,
        )
        baud_combo.pack(side=tk.LEFT, padx=(5, 0))

        # 第 1 行：账号
        row1 = ttk.Frame(main_frame)
        row1.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(row1, text="账  号:").pack(side=tk.LEFT)
        self.account_var = tk.StringVar(value="root")
        self.account_entry = ttk.Entry(
            row1, textvariable=self.account_var, width=30
        )
        self.account_entry.pack(side=tk.LEFT, padx=(5, 0))

        # 第 2 行：密码
        row2 = ttk.Frame(main_frame)
        row2.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row2, text="密  码:").pack(side=tk.LEFT)
        self.password_var = tk.StringVar(value="t*hEQ#BHu7z%3n")
        self.password_entry = ttk.Entry(
            row2, textvariable=self.password_var, show="*", width=30
        )
        self.password_entry.pack(side=tk.LEFT, padx=(5, 0))

        # 第 3 行：停止按钮 + 状态
        row3 = ttk.Frame(main_frame)
        row3.pack(fill=tk.X, pady=(0, 5))
        self.stop_btn = ttk.Button(
            row3,
            text="停止",
            command=self._stop_upgrade,
            state=tk.DISABLED,
            width=10,
        )
        self.stop_btn.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            row3, textvariable=self.status_var, foreground="gray"
        ).pack(side=tk.RIGHT)

        # 进度条
        self.progress = ttk.Progressbar(main_frame, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(0, 5))

    def _build_common_bottom(self, parent):
        """底部公共区：执行日志。任何 Tab 都看得到。"""
        log_frame = ttk.LabelFrame(parent, text="执行日志", padding="5")
        log_frame.pack(
            fill=tk.BOTH, expand=False, padx=10, pady=(0, 10)
        )

        self.log_area = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # 串口升级 Tab
    # ------------------------------------------------------------------
    def _build_upgrade_ui(self, parent):
        """串口升级 Tab 的 Tab 私有字段。

        公共部分（COM 端口、账号密码、状态、进度条、停止按钮、日志）已
        挪到 `_build_common_top` / `_build_common_bottom`，任何 Tab 都看得到。
        这里只放：升级方式 / Boot 模式 IP / 进入 boot 方式 / 升级文件 / 开始升级。
        """
        main_frame = parent

        # 升级方式
        self.method_frame = ttk.Frame(main_frame)
        self.method_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(self.method_frame, text="升级方式:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value="页面升级")
        method_combo = ttk.Combobox(
            self.method_frame,
            textvariable=self.method_var,
            values=["页面升级", "tftp指令", "tftp put"],
            state="readonly",
            width=18,
        )
        method_combo.pack(side=tk.LEFT, padx=(5, 0))
        method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        # Boot 模式 IP（无论选哪种升级方式都显示）
        self.ip_frame = ttk.Frame(main_frame)
        self.ip_frame.pack(fill=tk.X, pady=(0, 5), after=self.method_frame)
        ttk.Label(self.ip_frame, text=" Boot模式IP:").pack(side=tk.LEFT)
        self.ip_var = tk.StringVar(value="192.168.1.1")
        self.ip_entry = ttk.Entry(
            self.ip_frame, textvariable=self.ip_var, width=30
        )
        self.ip_entry.pack(side=tk.LEFT, padx=(5, 0))

        # 进入 boot 方式
        boot_frame = ttk.Frame(main_frame)
        boot_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(boot_frame, text="进入boot:").pack(side=tk.LEFT)
        self.boot_var = tk.StringVar(value="输入回车")
        boot_combo = ttk.Combobox(
            boot_frame,
            textvariable=self.boot_var,
            values=["输入回车", "输入sdmc"],
            state="readonly",
            width=18,
        )
        boot_combo.pack(side=tk.LEFT, padx=(5, 0))

        # 升级文件
        row3 = ttk.Frame(main_frame)
        row3.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row3, text="升级文件:").pack(side=tk.LEFT)
        self.filepath_var = tk.StringVar()
        self.filepath_entry = ttk.Entry(
            row3, textvariable=self.filepath_var, width=40
        )
        self.filepath_entry.pack(side=tk.LEFT, padx=(5, 5))
        self.browse_btn = ttk.Button(
            row3, text="浏览", width=6, command=self._browse_file
        )
        self.browse_btn.pack(side=tk.LEFT)

        # 开始升级按钮（"停止"按钮已挪到公共区）
        row4 = ttk.Frame(main_frame)
        row4.pack(fill=tk.X, pady=(0, 10))
        self.start_btn = ttk.Button(
            row4, text="开始升级", command=self._start_upgrade, width=20
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

    # ------------------------------------------------------------------
    # 写参工具 Tab
    # ------------------------------------------------------------------
    def _build_param_ui(self, parent):
        """写参工具 Tab：
        - 第一栏：参数表格文件（带浏览按钮）
        - 第二栏：增加参数按钮
        - 下方：默认 13 个写参栏（指令输入框 + 参数值输入框），可滚动
        """
        # ── 第一栏：参数表格 ─────────────────────────────────────────
        self.table_row = ttk.Frame(parent)
        self.table_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(self.table_row, text="参数表格:").pack(side=tk.LEFT)
        self.param_table_var = tk.StringVar()
        self.param_table_entry = ttk.Entry(
            self.table_row, textvariable=self.param_table_var, width=50
        )
        self.param_table_entry.pack(side=tk.LEFT, padx=(5, 5))
        self.param_browse_btn = ttk.Button(
            self.table_row, text="浏览", width=6, command=self._browse_param_table
        )
        self.param_browse_btn.pack(side=tk.LEFT)

        # ── 第二栏：增加参数 + 写入参数 按钮 ──────────────────────────
        action_row = ttk.Frame(parent)
        action_row.pack(fill=tk.X, pady=(0, 10))
        self.add_param_btn = ttk.Button(
            action_row, text="增加参数", width=12, command=self._add_param_row
        )
        self.add_param_btn.pack(side=tk.LEFT)
        self.write_param_btn = ttk.Button(
            action_row, text="写入参数", width=12, command=self._start_write_params
        )
        self.write_param_btn.pack(side=tk.LEFT, padx=(10, 0))

        # ── 写参栏容器（可滚动） ────────────────────────────────────
        params_outer = ttk.Frame(parent)
        params_outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(params_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            params_outer, orient=tk.VERTICAL, command=canvas.yview
        )
        self.params_container = ttk.Frame(canvas)
        self.params_container.bind(
            "<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.params_container, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 配置容器内的 grid 列宽，保证每行四列严格对齐
        self.params_container.columnconfigure(0, minsize=130)  # 标签
        self.params_container.columnconfigure(1, minsize=340)  # 写参指令
        self.params_container.columnconfigure(2, minsize=30)   # "值:" 标签
        self.params_container.columnconfigure(3, minsize=180)  # 参数值

        # 默认行（DEFAULT_PARAM_ROWS 中的标签 + 指令）
        self.param_rows = []  # 每项: (cmd_var, value_var)
        for label, cmd in DEFAULT_PARAM_ROWS:
            self._add_param_row(label, cmd)

    def _add_param_row(self, label_text="", cmd_text=""):
        """在容器最下方新增一个写参栏（标签 + 写参指令输入框 + 参数值输入框）"""
        row_idx = len(self.param_rows)

        ttk.Label(self.params_container, text=label_text).grid(
            row=row_idx, column=0, sticky="w", padx=(0, 6), pady=2
        )

        cmd_var = tk.StringVar(value=cmd_text)
        ttk.Entry(self.params_container, textvariable=cmd_var).grid(
            row=row_idx, column=1, sticky="ew", padx=(0, 10), pady=2
        )

        ttk.Label(self.params_container, text="值:").grid(
            row=row_idx, column=2, sticky="e", padx=(0, 4), pady=2
        )

        value_var = tk.StringVar()
        ttk.Entry(self.params_container, textvariable=value_var).grid(
            row=row_idx, column=3, sticky="ew", pady=2
        )

        self.param_rows.append((cmd_var, value_var))

    # ------------------------------------------------------------------
    # 写参流程
    # ------------------------------------------------------------------
    def _start_write_params(self):
        """点击"写入参数"按钮回调：开串口 + 启动后台写参线程"""
        if self.writing_params:
            return
        if self.upgrading:
            messagebox.showwarning(
                "提示", "升级正在进行中，请等待结束或停止后再写参。"
            )
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("提示", "请先选择 COM 端口")
            return

        try:
            baudrate = int(self.baud_var.get())
            self.serial_conn = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=DEFAULT_TIMEOUT,
                write_timeout=2,
            )
        except Exception as e:
            messagebox.showerror("串口错误", f"无法打开 {port}:\n{e}")
            return

        self._log(f"串口 {port} 已打开, 波特率 {baudrate}")
        self._log("========== 写参流程启动 ==========")

        # 升级 Tab 的账号密码（即 _start_upgrade 用的那两个）由调用方传入
        account = self.account_var.get().strip()
        password = self.password_var.get()

        self.writing_params = True
        self.write_param_btn.configure(state=tk.DISABLED)

        thread = threading.Thread(
            target=self._write_params_thread,
            args=(account, password),
            daemon=True,
        )
        thread.start()

    def _write_params_thread(self, account, password):
        """写参后台线程"""
        try:
            time.sleep(0.3)
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()

            # ── 1. 登录（使用升级页面的账号密码） ───────────────────
            self._log("--- 等待登录提示 ---")
            login_ok = self._serial_login(account, password)
            if not login_ok:
                self._log("!!! 登录失败")
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "写参失败", "登录失败，请检查账号密码或设备状态"
                    ),
                )
                self._close_serial()
                self.root.after(0, self._reset_write_ui)
                return
            self._log("--- 登录成功 ---")

            # ── 2. ppctl clear ────────────────────────────────────
            self._log("--- 发送 ppctl clear ---")
            self._serial_send_command("ppctl clear", wait=2.0)

            # ── 3. ppctl set FACTORY_MODE=1 ───────────────────────
            self._log("--- 发送 ppctl set FACTORY_MODE=1 ---")
            self._serial_send_command("ppctl set FACTORY_MODE=1", wait=2.0)

            # ── 4. firstboot -yr ──────────────────────────────────
            self._log("--- 发送 firstboot -yr ---")
            self._serial_send_command("firstboot -yr", wait=2.0)

            # ── 5. 等待 100s 设备重启 ────────────────────────────
            self._log("--- 等待 100s 启动完成 ---")
            total_wait = 100
            for remain in range(total_wait, 0, -1):
                if not self.writing_params:
                    self._log("!!! 写参已中断")
                    self._close_serial()
                    self.root.after(0, self._reset_write_ui)
                    return
                time.sleep(1)
                if remain % 10 == 0 or remain <= 5:
                    self._log(f"剩余等待 {remain}s")

            # ── 6. 串口输入回车 ──────────────────────────────────
            self._log("--- 发送回车 ---")
            self.serial_conn.write(b"\r\n")
            time.sleep(1.5)
            output = self._read_serial(timeout=1.0)
            if output.strip():
                self._log(f"[回显] {output.strip()[:200]}")

            # ── 7. 二次登录（root / FACTORY_PASSWORD） ─────────────
            self._log(f"--- 二次登录 ({FACTORY_ACCOUNT}) ---")
            login_ok = self._serial_login(FACTORY_ACCOUNT, FACTORY_PASSWORD)
            if not login_ok:
                self._log("!!! 二次登录失败")
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "写参失败",
                        "二次登录失败，请确认 FACTORY_PASSWORD 与设备一致",
                    ),
                )
                self._close_serial()
                self.root.after(0, self._reset_write_ui)
                return
            self._log("--- 二次登录成功，开始写参 ---")

            # ── 8. 依次发送写参指令 ─────────────────────────────
            written = 0
            skipped_empty = 0
            failed = 0
            failed_labels = []
            for i, (cmd_var, value_var) in enumerate(self.param_rows):
                if not self.writing_params:
                    self._log("!!! 写参已中断")
                    self._close_serial()
                    self.root.after(0, self._reset_write_ui)
                    return

                cmd = cmd_var.get().strip()
                value = value_var.get().strip()
                if not cmd:
                    continue
                if not value:
                    # 参数值为空：不发该项参数指令
                    self._log(f"[跳过] {cmd}  (参数值为空，不下发)")
                    skipped_empty += 1
                    continue

                full_cmd = self._build_write_command(cmd, value, i)
                if not full_cmd:
                    continue

                self._log(f">>> {full_cmd}")
                # 写 + 读回校验（最多 3 次失败重试）
                success, _ = self._write_and_verify_param(
                    cmd, value, i, max_attempts=3
                )
                if success:
                    written += 1
                else:
                    failed += 1
                    failed_labels.append(DEFAULT_PARAM_ROWS[i][0])

            self._log(
                f"--- 写参循环结束：写入 {written} 项 / "
                f"跳过 {skipped_empty} 项（值空） / "
                f"失败 {failed} 项 ---"
            )

            if failed > 0:
                failed_list = "\n".join(failed_labels)
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "写参失败",
                        f"以下 {failed} 项参数重试 3 次仍未生效：\n\n"
                        f"{failed_list}\n\n"
                        "请检查设备状态、链路或人工重试。",
                    ),
                )

            # ── 9. 退出工厂模式 ──────────────────────────────────
            self._log("--- 发送 ppctl set FACTORY_MODE=0 ---")
            self._serial_send_command("ppctl set FACTORY_MODE=0", wait=2.0)
            self._log("--- 发送 firstboot -yr ---")
            self._serial_send_command("firstboot -yr", wait=2.0)

            self._log(
                f"========== 写参完成：写入 {written} 项 / "
                f"跳过 {skipped_empty} 项 =========="
            )

        except serial.SerialException as e:
            self._log(f"!!! 串口异常: {e}")
        except Exception as e:
            self._log(f"!!! 未知错误: {e}")
        finally:
            self._close_serial()
            self.root.after(0, self._reset_write_ui)

    def _reset_write_ui(self):
        """恢复写参 UI 到初始状态"""
        self.writing_params = False
        try:
            self.write_param_btn.configure(state=tk.NORMAL)
        except Exception:
            pass

    def _build_write_command(self, cmd, value, index):
        """构造完整写参指令：cmd + "=\\"值\\""。
        MAC 标签特殊处理：转大写、以冒号分隔的 6 段格式（XX:XX:XX:XX:XX:XX）。
        """
        if not cmd.endswith("="):
            # 没有 '=' 后缀无法拼接，直接用 value 包引号
            return f'{cmd}"{value}"'

        label = ""
        if 0 <= index < len(DEFAULT_PARAM_ROWS):
            label = DEFAULT_PARAM_ROWS[index][0]

        if label == "MAC":
            # 提取十六进制字符（大写），然后 2 个一组加冒号
            cleaned = "".join(ch.upper() for ch in value if ch.isalnum())
            if len(cleaned) == 12:
                formatted = ":".join(
                    cleaned[k:k + 2] for k in range(0, 12, 2)
                )
                return f'{cmd}"{formatted}"'
            # 长度不合法，保留原值（避免直接丢数据）
            return f'{cmd}"{value}"'

        return f'{cmd}"{value}"'

    # ---- 写参校验辅助（set → get 读回比对） ----------------------

    def _normalize_mac_for_compare(self, value):
        """归一 MAC：去非字母数字字符 → 大写 → XX:XX:XX:XX:XX:XX。
        非 12 位合法 hex 时返回 None，让上层用原始字符串比较。
        """
        cleaned = "".join(ch.upper() for ch in value if ch.isalnum())
        if len(cleaned) != 12:
            return None
        return ":".join(cleaned[k:k + 2] for k in range(0, 12, 2))

    def _build_read_command(self, cmd):
        """从写指令构造读指令：'ppctl set SERIAL_NUMBER=' → 'ppctl get SERIAL_NUMBER'"""
        stripped = cmd[:-1] if cmd.endswith("=") else cmd
        return stripped.replace("set ", "get ", 1)

    def _read_back_value(self, read_cmd, var_name):
        """发送读指令，从设备回显里解析 VAR=... / VAR = ... / VAR: ... 等格式。
        成功返回字符串（已去引号），失败返回 None。
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        try:
            self.serial_conn.write((read_cmd + "\r\n").encode("utf-8"))
            time.sleep(0.6)  # 等设备开始响应
            output = self._read_serial(timeout=2.0)
        except Exception:
            return None
        if not output.strip():
            return None

        prefixes = [f"{var_name}=", f"{var_name} =", f"{var_name}:"]
        for raw in output.splitlines():
            line = raw.strip()
            for prefix in prefixes:
                if line.startswith(prefix):
                    value_part = line[len(prefix):].strip()
                    if len(value_part) >= 2 and value_part.startswith(
                        '"'
                    ) and value_part.endswith('"'):
                        value_part = value_part[1:-1]
                    return value_part
        return None

    def _write_and_verify_param(self, cmd, value, index, max_attempts=3):
        """写一条参数 → 读回校验 → 不一致则重试，最多 max_attempts 次。
        返回 (success: bool, attempts_used: int)。
        """
        label = ""
        if 0 <= index < len(DEFAULT_PARAM_ROWS):
            label = DEFAULT_PARAM_ROWS[index][0]

        # 计算"期望值"，MAC 走归一化
        if label == "MAC":
            expected = self._normalize_mac_for_compare(value) or value
        else:
            expected = value

        # 构造读指令 + 变量名（供解析回显）
        read_cmd = self._build_read_command(cmd)
        var_name = cmd.rstrip("=").rsplit(" ", 1)[-1]

        for attempt in range(1, max_attempts + 1):
            if not self.writing_params:
                return False, attempt - 1

            # 写
            write_cmd = self._build_write_command(cmd, value, index)
            if not write_cmd:
                return False, attempt
            self._log(f"[{attempt}/{max_attempts}] 写: {write_cmd}")
            self._serial_send_command(write_cmd, wait=1.0)

            # 读
            self._log(f"[{attempt}/{max_attempts}] 读: {read_cmd}")
            actual = self._read_back_value(read_cmd, var_name)
            if actual is None:
                self._log(f"[{attempt}/{max_attempts}] 读回无响应")
                continue

            self._log(f"[{attempt}/{max_attempts}] 读回值: {actual}")

            # MAC 走大小写/冒号归一比较；其他走字符串等值
            if label == "MAC":
                actual_norm = self._normalize_mac_for_compare(actual) or actual
                ok = expected.upper() == actual_norm.upper()
            else:
                actual_unq = actual.strip()
                if (
                    len(actual_unq) >= 2
                    and actual_unq.startswith('"')
                    and actual_unq.endswith('"')
                ):
                    actual_unq = actual_unq[1:-1]
                ok = actual_unq == expected

            if ok:
                self._log(
                    f"[OK] {label}: 写入={expected} 设备值={actual} "
                    f"(第 {attempt} 次)"
                )
                return True, attempt

            self._log(
                f"[不一致] {label}: 期望={expected} 设备={actual}"
            )

        return False, max_attempts

    def _browse_param_table(self):
        """选择本地参数表格，选完后解析其 MAC 列填到下拉框"""
        filepath = filedialog.askopenfilename(title="选择参数表格")
        if not filepath:
            return
        self.param_table_var.set(filepath)
        self._load_param_table(filepath)

    def _load_param_table(self, filepath):
        """读取参数表格 → 找 MAC 列 → 提取值 → 显示下拉框"""
        ext = filepath.lower().rsplit(".", 1)[-1] if "." in filepath else ""

        if ext in ("xlsx", "xlsm"):
            rows = self._read_xlsx_rows(filepath)
        elif ext == "xls":
            messagebox.showinfo(
                "暂不支持 .xls",
                "旧版 Excel (.xls) 请先用 Excel 另存为 .xlsx 或 .csv 后再加载。",
            )
            return
        else:
            rows = self._read_text_rows(filepath)

        if rows is None:
            return  # 错误已弹

        # 缓存整张表，给后续按 MAC 查行用
        self._table_rows = rows

        # ── 共用：找 MAC 列、提取去重 ─────────────────────────────
        if len(rows) < 2:
            messagebox.showinfo(
                "提示", "参数表格行数少于 2 行，无法提取 MAC 列表。"
            )
            return

        header = rows[0]
        mac_col = None
        for i, cell in enumerate(header):
            if str(cell).strip().upper() == "MAC":
                mac_col = i
                break
        if mac_col is None:
            preview = ", ".join(str(c).strip() for c in header[:8])
            messagebox.showinfo(
                "提示",
                f"参数表格第一行未找到 MAC 列。\n第一行前 8 列内容：{preview}",
            )
            return

        mac_values = []
        seen = set()
        for row in rows[1:]:
            if mac_col >= len(row):
                continue
            value = str(row[mac_col]).strip()
            if value and value not in seen:
                mac_values.append(value)
                seen.add(value)

        if not mac_values:
            messagebox.showinfo("提示", "MAC 列下没有可用的值。")
            return

        self._show_mac_combobox(mac_values)

    def _read_xlsx_rows(self, filepath):
        """用 openpyxl 读取 .xlsx/.xlsm → 返回 list[list[str]]。
        出错时已弹错误框，返回 None。
        """
        if not HAS_OPENPYXL:
            messagebox.showerror(
                "缺少依赖",
                "读取 Excel 文件需要安装 openpyxl：\n\n"
                "pip install openpyxl",
            )
            return None
        try:
            wb = openpyxl.load_workbook(
                filepath, read_only=True, data_only=True
            )
        except Exception as e:
            messagebox.showerror("读取 Excel 文件失败", str(e))
            return None
        try:
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([("" if v is None else str(v).strip()) for v in row])
        finally:
            wb.close()
        return rows

    def _read_text_rows(self, filepath):
        """以二进制读 → 去 NULL → 多编码兜底 → csv 解析。
        出错时已弹错误框，返回 None。
        """
        last_err = None
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
        except OSError as e:
            messagebox.showerror("读取参数表格失败", str(e))
            return None
        raw = raw.replace(b"\x00", b"")

        rows = None
        for encoding in ("utf-8-sig", "utf-8", "gbk", "gb2312", "latin-1"):
            try:
                text = raw.decode(encoding)
                if not text.strip():
                    rows = []
                    break
                sample = text[:8192]
                try:
                    dialect = csv.Sniffer().sniff(
                        sample, delimiters=",\t;|"
                    )
                except csv.Error:
                    dialect = csv.excel
                rows = list(csv.reader(text.splitlines(), dialect))
                break
            except UnicodeDecodeError as e:
                last_err = e
                continue

        if rows is None:
            messagebox.showerror(
                "读取参数表格失败",
                f"无法识别文件编码：{last_err}\n\n"
                "请确认是 CSV / TSV / 文本表格，且首行包含名为 MAC 的列。",
            )
        return rows

    def _show_mac_combobox(self, mac_values):
        """创建或更新 MAC 地址下拉框（始终插在参数表格行正下方）"""
        existing = getattr(self, "mac_row", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    # 复用已有控件，仅刷新值
                    self.mac_combo["values"] = mac_values
                    self.mac_var.set("")
                    return
            except Exception:
                pass

        self.mac_row = ttk.Frame(self.param_tab)
        self.mac_row.pack(fill=tk.X, pady=(0, 10), after=self.table_row)
        ttk.Label(self.mac_row, text="MAC 地址:").pack(side=tk.LEFT)
        self.mac_var = tk.StringVar()
        self.mac_combo = ttk.Combobox(
            self.mac_row,
            textvariable=self.mac_var,
            values=mac_values,
            state="readonly",
            width=40,
        )
        self.mac_combo.pack(side=tk.LEFT, padx=(5, 0))
        # 选中即触发：读表头与对应行 → 填到写参栏
        self.mac_combo.bind("<<ComboboxSelected>>", self._on_mac_selected)

    def _on_mac_selected(self, _event=None):
        """MAC 下拉框选中回调：
        1) 取第一行为 header（list）
        2) 取选中 MAC 那一行为 data row（list）
        3) 按 DEFAULT_PARAM_ROWS 中 cmd 的变量名匹配 → 填到对应写参栏的值
        """
        selected_mac = self.mac_var.get().strip()
        if not selected_mac:
            return

        rows = getattr(self, "_table_rows", None)
        if not rows:
            messagebox.showinfo("提示", "请先加载参数表格。")
            return

        header = [str(c).strip() for c in rows[0]]

        # 找 header 中名为 "MAC" 的列，先按该列精确匹配
        mac_col = None
        for i, cell in enumerate(header):
            if cell.upper() == "MAC":
                mac_col = i
                break

        matched_row = None
        if mac_col is not None:
            for row in rows[1:]:
                if mac_col >= len(row):
                    continue
                if str(row[mac_col]).strip() == selected_mac:
                    matched_row = row
                    break
        if matched_row is None:
            # fallback：整行任意一格等于该 MAC
            for row in rows[1:]:
                for cell in row:
                    if str(cell).strip() == selected_mac:
                        matched_row = row
                        break
                if matched_row is not None:
                    break

        if matched_row is None:
            messagebox.showwarning(
                "未找到对应行",
                f"在参数表格中没找到 MAC = {selected_mac} 的行。",
            )
            return

        data_row = [str(c).strip() for c in matched_row]

        # 存为实例变量（用户可直接读 self._table_header_row / self._table_matched_row）
        self._table_header_row = header
        self._table_matched_row = data_row

        # 按 PARAM_HEADER_MAP 把表头列值填到对应写参栏，MAC 字段直接用选中值
        self._fill_param_values(header, data_row, selected_mac)

    def _fill_param_values(self, header, data_row, selected_mac):
        """按 PARAM_HEADER_MAP 找表头列 → 把 data_row[col] 写到对应写参栏。
        MAC 走特殊值（直接用 selected_mac）。
        """
        param_rows = getattr(self, "param_rows", None)
        if not param_rows:
            return

        # 表头列名 → 列下标（大小写不敏感）
        lookup = {h.upper(): i for i, h in enumerate(header)}

        filled = []
        unmatched = []
        for i, (label, _) in enumerate(DEFAULT_PARAM_ROWS):
            if i >= len(param_rows):
                break

            target = PARAM_HEADER_MAP.get(label)
            if target is None:
                continue

            _, value_var = param_rows[i]

            if target == "__SELECTED_MAC__":
                value = selected_mac
            else:
                col_idx = lookup.get(target.upper())
                if col_idx is None or col_idx >= len(data_row):
                    unmatched.append(f"{label} (期望表头列：{target})")
                    continue
                value = str(data_row[col_idx]).strip()

            value_var.set(value)
            filled.append(f"{label}={value}")

        if filled or unmatched:
            parts = []
            if filled:
                parts.append(
                    "已填 " + str(len(filled)) + " 项：\n"
                    + "\n".join(filled)
                )
            if unmatched:
                parts.append(
                    "未匹配 " + str(len(unmatched)) + " 项：\n"
                    + "\n".join(unmatched)
                    + "\n\n（参数表格第一行的列名应与 PARAM_HEADER_MAP 中的期望列名一致）"
                )
            messagebox.showinfo("参数填充结果", "\n\n".join(parts))

    # ------------------------------------------------------------------
    # 串口端口刷新
    # ------------------------------------------------------------------
    def _refresh_ports(self):
        """扫描系统中可用的串口"""
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in sorted(ports)]
        self.port_combo["values"] = port_list
        if port_list and not self.port_var.get():
            self.port_var.set(port_list[0])
        self._log(f"检测到 {len(port_list)} 个串口: {', '.join(port_list) if port_list else '无'}")

    def _browse_file(self):
        """选择本地升级文件"""
        filepath = filedialog.askopenfilename(title="选择升级文件")
        if filepath:
            self.filepath_var.set(filepath)

    def _on_method_change(self, _event=None):
        """升级方式切换回调（保留为 combobox 绑定入口）。

        IP 行已统一常显（任何升级方式都需要用到设备 IP），所以这里不再做
        show/hide，仅作为占位回调存在。
        """
        pass

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        """在日志窗口追加一条带时间戳的消息（线程安全）"""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"

        def _append():
            self.log_area.configure(state=tk.NORMAL)
            self.log_area.insert(tk.END, line)
            self.log_area.see(tk.END)
            self.log_area.configure(state=tk.DISABLED)

        self.root.after(0, _append)

    def _set_status(self, text: str, color: str = "gray"):
        """更新状态栏"""
        self.root.after(0, lambda: self.status_var.set(text))
        self.root.after(0, lambda: self.status_var.configure(foreground=color))

    # ------------------------------------------------------------------
    # 升级流程
    # ------------------------------------------------------------------
    def _start_upgrade(self):
        """开始升级按钮回调"""
        port = self.port_var.get().strip()
        account = self.account_var.get().strip()
        password = self.password_var.get()

        # 参数校验
        if not port:
            messagebox.showwarning("提示", "请先选择 COM 端口")
            return
        if not account:
            messagebox.showwarning("提示", "请输入账号")
            return

        # 使用硬编码指令
        commands = list(HARDCODED_COMMANDS)
        if not commands:
            messagebox.showerror("错误", "没有有效命令")
            return

        # 尝试打开串口
        try:
            baudrate = int(self.baud_var.get())
            self.serial_conn = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=DEFAULT_TIMEOUT,
                write_timeout=2,
            )
        except Exception as e:
            messagebox.showerror("串口错误", f"无法打开 {port}:\n{e}")
            return

        self._log(f"串口 {port} 已打开, 波特率 {baudrate}")
        self._log(f"已加载 {len(commands)} 条指令")

        # 切换 UI 状态
        self.upgrading = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.refresh_btn.configure(state=tk.DISABLED)
        self.progress["maximum"] = len(commands) + 2  # +2 for login
        self.progress["value"] = 0
        self._set_status("升级中...", "blue")

        # 获取升级文件路径
        file_path = self.filepath_var.get().strip()

        # 获取升级方式和 IP（页面升级时使用）
        method = self.method_var.get()
        device_ip = self.ip_var.get().strip() or "192.168.1.1"

        # 获取进入boot方式
        boot_method = self.boot_var.get()

        # 在后台线程执行
        thread = threading.Thread(
            target=self._upgrade_thread,
            args=(port, account, password, commands, file_path, method, device_ip, boot_method),
            daemon=True,
        )
        thread.start()

    def _stop_upgrade(self):
        """停止升级"""
        self.upgrading = False
        self._log("用户手动停止升级")
        self._set_status("已停止", "orange")
        self._close_serial()
        self._reset_ui()

    # ------------------------------------------------------------------
    # 进入 boot 的共用流程（输入回车 / 输入sdmc 两种模式都走这里）
    # ------------------------------------------------------------------
    def _is_boot_prompt(self, text):
        """检查串口回显里是否出现了 shell 提示符。

        支持的提示符：
          - "=>"        : 通用 U-Boot 风格
          - "ECNT>"     : Zyxel / Economal 风格
          - "U-Boot>"   : 旧版 U-Boot / 部分厂商自定义提示符
        """
        if not text:
            return False
        return (
            "=>" in text
            or "ECNT>" in text
            or "U-Boot>" in text
        )

    def _loop_until_prompt(self, send_bytes, send_label, max_retries=60):
        """循环发送 send_bytes 直到设备出现 UserName: 提示符或 =>/ECNT> 提示符。

        Returns:
            username_seen (bool): True 表示看到 UserName:，可以走登录
        """
        self._log(f"--- 等待设备重启，循环发送 {send_label} ---")
        count = 0
        username_seen = False
        while self.upgrading and count < max_retries:
            self._log(f">>> {send_label} [{count + 1}/{max_retries}]")
            self.serial_conn.write(send_bytes)
            time.sleep(1.0)
            output = self._read_serial(timeout=0.5)
            self._log(f"[串口接收 {len(output)} 字符]")
            if output.strip():
                display = output.strip()
                if len(display) > 500:
                    display = display[:500] + f"... <总 {len(display)} 字符>"
                self._log(f"[回显] {display}")
                # UserName: 必须满足两个条件才算真正的登录提示：
                #   1) 最后一行末尾是 "username:"
                #   2) 整段回显比较短（≤10 行），设备已停在提示符、不再喷启动日志
                lines = output.rstrip().splitlines()
                last_line = lines[-1] if lines else ""
                if (last_line.rstrip().lower().endswith("username:")
                        and len(lines) <= 10):
                    self._log("--- 检测到 UserName: 提示符 ---")
                    username_seen = True
                    break
                if self._is_boot_prompt(output):
                    self._log(
                        f"--- 检测到 shell 提示符，{send_label}已停止 ---"
                    )
                    break
            count += 1
        return username_seen

    def _do_boot_login(self, boot_username, boot_password):
        """看到 UserName: 后用 telecomadmin/nE7jA%5m 走登录流程。

        流程：发账号 → 等 Password → 发密码 → 再发回车 → 检测 shell 提示符（成功）
        或 UserName: 再次出现（凭据被拒，最多重试 3 次）。

        失败时会弹 messagebox 错误对话框。

        Returns:
            boot_ok (bool): True 表示成功进入 shell 提示符
        """
        boot_ok = False
        max_login_retries = 3
        for login_attempt in range(1, max_login_retries + 1):
            if not self.upgrading:
                break
            self._log(
                f"--- 登录尝试 [{login_attempt}/{max_login_retries}] ---"
            )

            # 发送用户名 + 边读边等 Password 提示（避免 echo 读吞掉 Password）
            # 注意：交互式输入只用 \r，不要 \n——本设备的 U-Boot console
            # 把 \r 当 Enter 提交，把 \n 落进下一字段当 stray 字节。
            self._log(f">>> 发送用户名: {boot_username}")
            self.serial_conn.write(
                (boot_username + "\r").encode("utf-8")
            )
            time.sleep(0.3)

            found, echo = self._read_until_prompt("assword:", timeout=10)
            self._log(f"[用户名+Password 回显 {len(echo)} 字符]")
            if echo.strip():
                display = echo.strip()
                if len(display) > 500:
                    display = display[:500] + f"... <总 {len(display)} 字符>"
                self._log(f"[回显] {display}")
            if not found:
                self._log("!!! 未检测到 Password 提示符，停止重试")
                break

            # 发送密码 + 读 echo（同样只用 \r，避免 stray）
            self._log("--- 检测到 Password 提示符 ---")
            self.serial_conn.write(
                (boot_password + "\r").encode("utf-8")
            )
            time.sleep(1.0)
            echo = self._read_serial(timeout=0.5)
            self._log(f"[密码后回显 {len(echo)} 字符]")
            if echo.strip():
                display = echo.strip()
                if len(display) > 500:
                    display = display[:500] + f"... <总 {len(display)} 字符>"
                self._log(f"[密码回显] {display}")

            # 在密码 echo 里立刻判定三种结果：
            #   1) 末尾 UserName: → 凭据被拒，saw_reprompt = True
            #   2) 出现 shell 提示符 → 登录成功，boot_ok = True
            #   3) 都不是 → 进入"多发回车"流程
            saw_reprompt = False
            echo_lines = echo.rstrip().splitlines()
            echo_last = echo_lines[-1] if echo_lines else ""
            if (
                echo_last.rstrip().lower().endswith("username:")
                and len(echo_lines) <= 10
            ):
                self._log(
                    f"--- [{login_attempt}/{max_login_retries}] "
                    "密码回显中即检测到 UserName: → 登录被拒 ---"
                )
                saw_reprompt = True
            elif self._is_boot_prompt(echo):
                self._log(
                    f"--- [{login_attempt}/{max_login_retries}] "
                    "密码回显中即检测到 shell 提示符 → 登录成功 ---"
                )
                boot_ok = True

            if not saw_reprompt and not boot_ok:
                # 输入密码后再额外发送一个回车 + 读 echo
                self._log(">>> 输入回车")
                self.serial_conn.write(b"\r\n")
                time.sleep(1.5)
                echo = self._read_serial(timeout=0.5)
                self._log(f"[回车后回显 {len(echo)} 字符]")
                if echo.strip():
                    display = echo.strip()
                    if len(display) > 500:
                        display = display[:500] + f"... <总 {len(display)} 字符>"
                    self._log(f"[回车回显] {display}")
                # 同样在这段 echo 里查 shell 提示符
                if self._is_boot_prompt(echo):
                    self._log(
                        f"--- [{login_attempt}/{max_login_retries}] "
                        "回车后回显中即检测到 shell 提示符 → 登录成功 ---"
                    )
                    boot_ok = True

            if boot_ok:
                self._log("--- 进入boot成功 ---")
                break

            if saw_reprompt and login_attempt < max_login_retries:
                time.sleep(1.0)
                continue

            # 进入 10 次等 shell 循环
            if not saw_reprompt and not boot_ok:
                for i in range(10):
                    output = self._read_serial(timeout=1.0)
                    self._log(
                        f"[等shell {i + 1}/10 收 {len(output)} 字符]"
                    )
                    if output.strip():
                        display = output.strip()
                        if len(display) > 500:
                            display = display[:500] + f"... <总 {len(display)} 字符>"
                        self._log(f"[回显] {display}")
                        if self._is_boot_prompt(output):
                            boot_ok = True
                            break
                        lines = output.rstrip().splitlines()
                        last_line = lines[-1] if lines else ""
                        if (
                            last_line.rstrip().lower().endswith("username:")
                            and len(lines) <= 10
                        ):
                            self._log(
                                f"--- [{login_attempt}/{max_login_retries}] "
                                "检测到 UserName: 再次出现 → 登录失败 ---"
                            )
                            saw_reprompt = True
                            break
                    else:
                        time.sleep(0.5)

            if boot_ok:
                self._log("--- 进入boot成功 ---")
                break

            if saw_reprompt and login_attempt < max_login_retries:
                time.sleep(1.0)
                continue

            # 10 次读都没出结果 → 放弃
            break

        if not boot_ok:
            self._log("!!! 进入boot失败：未检测到 shell 提示符")
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "进入boot失败",
                    "重试 3 次仍未进入 shell 提示符\n请检查账号密码或设备状态",
                ),
            )
        return boot_ok

    # ------------------------------------------------------------------
    # tftp指令 升级流程：起 tftp 服务器 + 复制文件 + 串口发 tftp 拉文件
    # ------------------------------------------------------------------
    def _find_tftp_server(self):
        """查找本机 tftp 服务器程序（tftpd64 / tftpd32 / SolarWinds TFTP 等）。

        Returns:
            完整可执行路径；找不到返回 None。
        """
        # 常见安装路径
        candidates = [
            r"C:\Program Files\Tftpd64\tftpd64.exe",
            r"C:\Program Files (x86)\Tftpd64\tftpd64.exe",
            r"C:\Program Files\Tftpd32\tftpd32.exe",
            r"C:\Program Files (x86)\Tftpd32\tftpd32.exe",
            r"C:\Program Files\SolarWinds\TFTP-Server\TFTPServer.exe",
            r"C:\Program Files (x86)\SolarWinds\TFTP-Server\TFTPServer.exe",
            r"D:\Tftpd64\tftpd64.exe",
            r"D:\Tools\Tftpd64\tftpd64.exe",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path

        # 用户提供的本地工具：当前工作目录下的 TFTPD322_NEW/tftpd32.exe
        local_tool = os.path.join(os.getcwd(), "TFTPD322_NEW", "tftpd32.exe")
        if os.path.exists(local_tool):
            return local_tool

        # Fallback: 用 where 命令找
        try:
            result = subprocess.run(
                ["where", "tftpd64"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass

        return None

    def _set_tftpd_base_dir(self, tftpd_path, base_dir):
        """把 tftpd32.ini 里的 BaseDirectory 改成 base_dir。

        tftpd_path: tftpd32.exe 完整路径（ini 在它的同目录下）
        base_dir:  新的 BaseDirectory 值（升级文件所在目录）

        Returns:
            True 成功；False 失败。
        """
        ini_path = os.path.join(os.path.dirname(tftpd_path), "tftpd32.ini")
        if not os.path.exists(ini_path):
            self._log(f"!!! 找不到 tftpd32.ini: {ini_path}")
            return False

        # 读所有行
        try:
            with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception as e:
            self._log(f"!!! 读 {ini_path} 失败: {e}")
            return False

        # 找 BaseDirectory 行（不区分大小写），没找到就标记后面要插入
        new_lines = []
        found = False
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("basedirectory="):
                new_lines.append(f"BaseDirectory={base_dir}\n")
                found = True
            else:
                new_lines.append(line)

        # 找不到就把 BaseDirectory 插到 [TFTP] 段后面
        if not found:
            inserted = False
            for i, line in enumerate(new_lines):
                if line.strip().upper() == "[TFTP]":
                    new_lines.insert(i + 1, f"BaseDirectory={base_dir}\n")
                    inserted = True
                    break
            if not inserted:
                # 没有 [TFTP] 段就追加到文件末尾
                new_lines.append(f"\n[TFTP]\nBaseDirectory={base_dir}\n")

        # 写回
        try:
            with open(ini_path, "w", encoding="utf-8", errors="ignore") as f:
                f.writelines(new_lines)
            return True
        except Exception as e:
            self._log(f"!!! 写 {ini_path} 失败: {e}")
            return False

    def _collect_local_ips(self):
        """多方法穷举本机所有 IPv4，返回去重列表。

        来源（按顺序追加，去重）：
          1. socket.gethostbyname_ex
          2. socket.getaddrinfo
          3. ipconfig /all（按 IPv4/IP Address/IP 地址 三关键词扫行）
          4. PowerShell Get-NetIPAddress（Windows 8+，最全，覆盖禁用/虚拟 NIC）

        第 4 步是关键——`gethostbyname_ex` 只回 hostname 绑定的 IP，`ipconfig`
        对没启用/没分配 hostname 的 NIC 也会漏，PowerShell 才能扫遍所有 NIC。
        """
        import socket
        import re as _re
        import subprocess

        all_ips = []

        def _add(ip):
            ip = (ip or "").strip()
            if (
                ip
                and ":" not in ip
                and not ip.startswith("127.")
                and not ip.startswith("0.0.0.0")
                and ip not in all_ips
            ):
                all_ips.append(ip)

        # 1. gethostbyname_ex
        try:
            _, _, ips = socket.gethostbyname_ex(socket.gethostname())
            for ip in ips:
                _add(ip)
        except Exception:
            pass

        # 2. getaddrinfo
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                _add(info[4][0])
        except Exception:
            pass

        # 3. ipconfig /all
        try:
            result = subprocess.run(
                ["ipconfig", "/all"],
                capture_output=True, text=True, timeout=10,
                encoding="gbk", errors="ignore"
            )
            for line in result.stdout.splitlines():
                if any(kw in line for kw in ("IPv4", "IP Address", "IP 地址")):
                    m = _re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                    if m:
                        _add(m.group(1))
        except Exception:
            pass

        # 4. PowerShell Get-NetIPAddress（Windows 8+ / Server 2012+）
        try:
            ps_cmd = (
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object { $_.IPAddress -notmatch '^127\\.' "
                "-and $_.IPAddress -ne '0.0.0.0' } | "
                "Select-Object -ExpandProperty IPAddress"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
                encoding="gbk", errors="ignore"
            )
            for line in result.stdout.splitlines():
                _add(line)
        except Exception as e:
            self._log(f"[_collect_local_ips] PowerShell 失败: {e}")

        return all_ips

    def _get_local_ip(self, device_ip):
        """遍历本机所有网卡 IP，找与 device_ip 同子网段（前三段相同）的 IPv4。

        Returns:
            IP 字符串；找不到返回 None。
        """
        subnet_prefix = ".".join(device_ip.split(".")[:3])
        prefix_dot = subnet_prefix + "."

        all_ips = self._collect_local_ips()

        for ip in all_ips:
            if ip.startswith(prefix_dot):
                return ip

        # 全部方法都查不到，把候选 IP 写日志
        self._log(
            f"[_get_local_ip] 未找到与 {subnet_prefix}.x 匹配的 IP，"
            f"本机所有 IPv4: {all_ips}"
        )
        return None

    def _get_all_local_ips(self):
        """返回本机所有 IPv4 列表（用于错误对话框展示）。"""
        return self._collect_local_ips()

    def _do_tftp_cmd_upgrade(self, device_ip, file_path):
        """tftp指令 升级：起 tftp 服务器 → 改 BaseDirectory 指向升级文件目录 → 串口发 tftp 拉文件。

        设备作为 tftp client 主动从本机 tftp server 拉升级文件。
        BaseDirectory 直接指向升级文件所在的目录（设备拉文件时 tftpd32 从该目录
        找文件），所以不再需要把文件再复制一份。
        """
        if not file_path or not os.path.exists(file_path):
            self._log(f"!!! 升级文件不存在: {file_path}")
            self.root.after(
                0,
                lambda: messagebox.showerror("文件不存在", f"升级文件不存在:\n{file_path}"),
            )
            return

        # 1. 找 tftp 服务器
        tftp_path = self._find_tftp_server()
        if not tftp_path:
            self._log("!!! 找不到 tftp 服务器程序（tftpd64 / tftpd32）")
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "tftp 服务器未找到",
                    "找不到 tftpd64 / tftpd32 等 TFTP 服务器程序。\n"
                    "请安装后重试，或把 tftpd64.exe 加入 PATH。",
                ),
            )
            return
        self._log(f"--- 找到 tftp 服务器: {tftp_path} ---")

        # 2. 改 tftpd32.ini 的 BaseDirectory → 升级文件所在目录
        upgrade_dir = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        self._log(f"--- 升级文件: {file_path}（所在目录 {upgrade_dir}）---")
        self._log(
            f"--- 改 {os.path.join(os.path.dirname(tftp_path), 'tftpd32.ini')} "
            f"的 BaseDirectory → {upgrade_dir} ---"
        )
        if not self._set_tftpd_base_dir(tftp_path, upgrade_dir):
            self._log("!!! 修改 tftpd32.ini 的 BaseDirectory 失败")
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "tftpd 配置失败",
                    "修改 tftpd32.ini 的 BaseDirectory 失败。\n"
                    "请检查 tftpd32.ini 是否可写、是否被占用。",
                ),
            )
            return

        # 3. 找本机同子网 IP
        local_ip = self._get_local_ip(device_ip)
        if not local_ip:
            subnet_prefix = ".".join(device_ip.split(".")[:3])
            all_ips = self._get_all_local_ips()
            self._log(
                f"!!! 找不到与设备 {device_ip} 同子网段（前缀 {subnet_prefix}）的本机 IP"
            )
            self._log(f"!!! 本机所有网卡 IPv4: {all_ips}")
            self.root.after(
                0,
                lambda: messagebox.showwarning(
                    "本机 IP 未找到",
                    f"找不到与设备 {device_ip} 同子网段（{subnet_prefix}.x）的本机 IP。\n\n"
                    f"本机所有网卡 IP：\n{chr(10).join(all_ips) if all_ips else '（未检测到任何 IP）'}\n\n"
                    "请检查网络设置：\n"
                    "  · PC 与设备是否在同一物理/逻辑网段\n"
                    "  · 设备 Boot 模式 IP（'Boot模式IP' 框）是否填对\n"
                    "  · 对应网卡是否已启用并分配了 IP",
                ),
            )
            return
        self._log(f"--- 本机 IP: {local_ip}（设备 {device_ip} 同子网）---")

        # 4. 启动 tftp 服务器（GUI 进程，让它在后台运行）
        self._log(f"--- 启动 tftp 服务器: {tftp_path} ---")
        try:
            self.tftp_process = subprocess.Popen(
                [tftp_path],
                creationflags=getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                ),
            )
        except Exception as e:
            self._log(f"!!! 启动 tftp 服务器失败: {e}")
            return
        # 等几秒让 tftp 服务器初始化（GUI 程序需要时间）
        time.sleep(3.0)

        # 5. 串口发 tftp 指令：tftp <local_ip>:<filename>
        #    例如：tftp 192.168.1.139:tclinux_allinone
        #    设备作为 tftp client 主动从本机 tftp server 拉升级文件。
        tftp_cmd = f"tftp {local_ip}:{filename}"
        self._log(f">>> {tftp_cmd}")
        self._serial_send_command(tftp_cmd, wait=5.0)

        # 6. 读回显（tftp 下载可能需要一段时间，设备会显示进度/完成信息）
        output = self._read_serial(timeout=15.0)
        if output.strip():
            self._log(f"[tftp 回显] {output.strip()[:500]}")
            if (
                "complete" in output.lower()
                or "done" in output.lower()
                or "success" in output.lower()
                or filename in output
            ):
                self._log("--- tftp 拉取完成（请查看设备日志确认）---")
            else:
                self._log("--- tftp 状态未知，请检查设备串口 ---")
        else:
            self._log("--- tftp 回执为空，请检查设备状态 ---")

    def _upgrade_thread(self, port: str, account: str, password: str, commands: list, file_path: str, method: str, device_ip: str, boot_method: str):
        """后台升级线程"""
        try:
            # 等待设备启动 / 清空缓冲区
            time.sleep(0.3)
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()

            # ── 登录阶段 ────────────────────────────────────────────
            self._log("--- 等待登录提示 ---")
            self.progress_step()

            login_ok = self._serial_login(account, password)
            if not login_ok:
                self._log("!!! 登录失败，请检查账号密码或设备状态")
                self._set_status("登录失败", "red")
                self._close_serial()
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "登录失败",
                        "未能检测到 OpenWrt:~# 提示符\n"
                        "请检查账号密码或设备状态",
                    ),
                )
                self.root.after(0, self._reset_ui)
                return

            self._log("--- 登录成功，发送 firstboot -yr ---")
            self.progress_step()

            # ── 仅保留最后一条指令 firstboot -yr ─────────────────
            if not self.upgrading:
                self._log("升级已被中断")
                return
            cmd = "firstboot -yr"
            self._log(f">>> {cmd}")
            self._serial_send_command(cmd)
            self.progress_step()

            # ── 等待设备重启进入 boot ─────────────────────────────────
            # boot_ok：成功进入 boot 模式（看到 shell 提示符）才为 True；
            # 否则下面的"根据升级方式选择后续流程"整段不执行，避免没进 boot
            # 就误发 tftp 指令 / 误开浏览器。
            boot_ok = False
            if boot_method == "输入回车":
                # 循环发送回车 → UserName: → 账号 → 密码 → shell
                username_seen = self._loop_until_prompt(b"\r\n", "回车")
                if username_seen:
                    boot_ok = self._do_boot_login("telecomadmin", "nE7jA%5m")
                else:
                    self._log("!!! 进入boot失败：未检测到 UserName: 提示符")
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "进入boot失败", "未检测到 UserName: 提示符"
                        ),
                    )
            elif boot_method == "输入sdmc":
                # 循环发送 sdmc → UserName: → 账号 → 密码 → shell
                # 账号密码与"输入回车"一致
                username_seen = self._loop_until_prompt(b"sdmc\r", "sdmc")
                if username_seen:
                    boot_ok = self._do_boot_login("telecomadmin", "nE7jA%5m")
                else:
                    self._log("!!! 进入boot失败：未检测到 UserName: 提示符")
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "进入boot失败", "未检测到 UserName: 提示符"
                        ),
                    )

            if not boot_ok:
                self._log("!!! 未进入 boot 模式，跳过升级动作 ---")
                return

            # ── 根据升级方式选择后续流程 ──────────────────────────────
            if method == "tftp put":
                # 在 cmd 中执行: tftp <设备 IP> put <升级文件路径>
                self._log("--- 已选择 [tftp put] 模式 ---")
                if not file_path:
                    self._log("!!! 未指定升级文件路径，无法执行 tftp put")
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "tftp put 失败", "未指定升级文件路径"
                        ),
                    )
                else:
                    tftp_cmd = f'tftp -i {device_ip} put "{file_path}"'
                    self._log(f"--- 在 cmd 中执行: {tftp_cmd} ---")
                    try:
                        result = subprocess.run(
                            tftp_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=600,
                        )
                        if result.stdout:
                            self._log(f"[tftp 输出] {result.stdout.strip()}")
                        if result.stderr:
                            self._log(f"[tftp 错误] {result.stderr.strip()}")
                        self._log(f"[tftp 返回码] {result.returncode}")
                        if result.returncode == 0:
                            self._log("--- tftp put 成功 ---")
                        else:
                            self._log("!!! tftp put 失败，请检查设备 IP 和文件路径")
                    except subprocess.TimeoutExpired:
                        self._log("!!! tftp put 执行超时（>10分钟）")
                        self.root.after(
                            0,
                            lambda: messagebox.showerror(
                                "tftp put 失败", "tftp put 执行超时"
                            ),
                        )
                    except FileNotFoundError:
                        self._log("!!! 系统未找到 tftp 命令，请确认 TFTP 客户端已启用")
                        self.root.after(
                            0,
                            lambda: messagebox.showerror(
                                "tftp put 失败",
                                "系统未找到 tftp 命令，请在 Windows 功能中启用 TFTP 客户端",
                            ),
                        )
                    except Exception as e:
                        self._log(f"!!! tftp put 异常: {e}")
                        self.root.after(
                            0,
                            lambda: messagebox.showerror(
                                "tftp put 失败", f"tftp put 异常: {e}"
                            ),
                        )
            elif method == "tftp指令":
                # 设备作为 tftp client，本机作为 tftp server 提供文件
                self._do_tftp_cmd_upgrade(device_ip, file_path)
            else:
                # ── Selenium 浏览器自动化 ─────────────────────────
                self._log(f"--- 启动浏览器访问 http://{device_ip} ---")
                driver = None
                try:
                    # 使用 webdriver-manager 自动下载匹配的 Edge WebDriver
                    service = Service(EdgeChromiumDriverManager().install())
                    driver = webdriver.Edge(service=service)
                    driver.maximize_window()
                    driver.get(f"http://{device_ip}")
                    self._log("浏览器已打开，等待页面加载...")
                    time.sleep(3)  # 等待页面完全渲染，便于观察

                    # 等待文件上传 input 元素出现
                    wait = WebDriverWait(driver, 15)
                    file_input = wait.until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="m"]/form/input[1]'))
                    )
                    self._log("--- 检测到文件选择按钮，传入升级文件路径 ---")
                    time.sleep(1)
                    if file_path:
                        file_input.send_keys(file_path)
                        self._log(f"已选择文件: {file_path}")
                        time.sleep(2)  # 等待页面处理文件选择
                    else:
                        self._log("!!! 未指定升级文件路径，跳过文件选择")

                    # 等待升级按钮出现并点击
                    self._log("--- 查找升级按钮 ---")
                    upgrade_btn = wait.until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="m"]/form/input[2]'))
                    )
                    time.sleep(1)
                    # 滚动到按钮可见位置
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", upgrade_btn)
                    time.sleep(0.5)
                    self._log("--- 点击升级按钮 ---")
                    try:
                        upgrade_btn.click()
                    except Exception:
                        # 普通 click 被拦截时，用 JS 方式点击
                        self._log("普通点击被拦截，改用 JS 点击")
                        driver.execute_script("arguments[0].click();", upgrade_btn)
                    self._log("升级指令已提交，请观察设备状态")
                    time.sleep(2)

                except Exception as e:
                    self._log(f"!!! 浏览器自动化失败: {e}")
                    self._log(f"请尝试手动访问 http://{device_ip} 完成升级")
                finally:
                    # 不关闭浏览器，让用户观察结果
                    pass

            self._log("========== 升级完成 ==========")
            self._set_status("升级完成", "green")

        except serial.SerialException as e:
            self._log(f"!!! 串口异常: {e}")
            self._set_status("串口异常", "red")
        except Exception as e:
            self._log(f"!!! 未知错误: {e}")
            self._set_status("错误", "red")
        finally:
            self._close_serial()
            self.root.after(0, self._reset_ui)

    # ------------------------------------------------------------------
    # 串口通信辅助
    # ------------------------------------------------------------------
    def _serial_login(self, account: str, password: str) -> bool:
        """
        通过串口登录设备：
          1) 先发回车预检，末尾以 OpenWrt:~# 收尾说明已登录，直接返回 True（不再发账号密码）
          2) 否则按 login: → 发账号 → Password: → 发密码 → 再发回车 → 末尾 OpenWrt:~# 走
        任何环节末尾不是 OpenWrt:~# 都视为登录失败，返回 False，由调用方提示用户。
        """
        # 1) 先发一个回车，看是否已经登录（设备已登录时回显末尾应是 OpenWrt:~#）
        self.serial_conn.write(b"\r\n")
        time.sleep(1.0)
        precheck = self._read_serial(timeout=2.0)
        precheck_lines = precheck.rstrip().splitlines()
        precheck_last = precheck_lines[-1] if precheck_lines else ""
        self._log(f"[登录预检回显] {precheck.strip()[-200:]}")
        if precheck_last.endswith("OpenWrt:~#"):
            self._log(
                "--- 已登录（预检即命中 OpenWrt:~#，跳过账号密码）---"
            )
            return True

        # 2) 未登录：等 login: → 发账号 → 等 Password → 发密码 → 再发回车 → 末尾判定
        # 等待 "login:" 并发送账号
        # 注意：交互式输入只用 \n，不要 \r——某些 TTY 把 \r 当 Enter，把 \n 落进
        # 下一字段当 stray 字节，导致密码校验前就被污染。
        self.serial_conn.write(b"\r\n")
        time.sleep(0.5)
        if not self._wait_for_prompt("ogin:", timeout=5):
            self._log("!!! 未检测到 login: 提示，尝试直接发送账号")
        self.serial_conn.write((account + "\n").encode("utf-8"))
        time.sleep(0.5)

        # 等待 "Password:" 并发送密码
        if not self._wait_for_prompt("assword:", timeout=5):
            self._log("!!! 未检测到 Password: 提示，尝试直接发送密码")
        self.serial_conn.write((password + "\n").encode("utf-8"))
        time.sleep(1.0)

        # 输入完账号密码后，再输入一个回车，触发 shell 提示
        self.serial_conn.write(b"\r\n")
        time.sleep(1.0)

        # 读回显，提取最后一行（去掉空白）做 OpenWrt:~# 判定
        output = self._read_serial(timeout=2.0)
        lines = output.rstrip().splitlines()
        last_line = lines[-1] if lines else ""
        self._log(f"[登录回显] {output.strip()[-200:]}")

        if last_line.endswith("OpenWrt:~#"):
            self._log("--- 登录成功（检测到 OpenWrt:~#）---")
            return True

        self._log(
            f"!!! 登录失败：回显末尾不是 OpenWrt:~#（末尾行：{last_line[:80]!r}）"
        )
        return False

    def _wait_for_prompt(self, prompt: str, timeout: float = 10) -> bool:
        """等待串口出现指定提示字符串"""
        start = time.time()
        buf = ""
        while time.time() - start < timeout:
            # 升级 / 写参 任一流程在跑就继续等；都没有说明线程已退出
            if not (self.upgrading or self.writing_params):
                return False
            chunk = self._read_serial(timeout=0.3)
            if chunk:
                buf += chunk
                if prompt.lower() in buf.lower():
                    return True
        return False

    def _read_until_prompt(self, prompt, timeout=10):
        """读取直到缓冲中出现 prompt 子串。
        返回 (found, accumulated) —— 把累计读到的 buffer 一并交给调用者打日志。
        相比 _wait_for_prompt 只返 True/False，这版解决了"读完 echo 就把 prompt 吞了"的 bug。
        """
        start = time.time()
        buf = ""
        while time.time() - start < timeout:
            if not (self.upgrading or self.writing_params):
                return False, buf
            chunk = self._read_serial(timeout=0.3)
            if chunk:
                buf += chunk
                if prompt.lower() in buf.lower():
                    return True, buf
        return False, buf

    def _serial_send_command(self, cmd: str, wait: float = 1.0):
        """发送一条命令并等待设备响应"""
        self.serial_conn.write((cmd + "\r\n").encode("utf-8"))
        time.sleep(wait)
        output = self._read_serial(timeout=0.5)
        if output.strip():
            # 截断过长输出
            display = output.strip()[:500]
            self._log(f"[回显] {display}")

    def _read_serial(self, timeout: float = 0.3) -> str:
        """从串口读取可用数据"""
        try:
            original_timeout = self.serial_conn.timeout
            self.serial_conn.timeout = timeout
            data = self.serial_conn.read(self.serial_conn.in_waiting or 1)
            # 继续读完剩余缓冲
            waiting = self.serial_conn.in_waiting
            if waiting:
                data += self.serial_conn.read(waiting)
            self.serial_conn.timeout = original_timeout

            # 尝试多种编码解码
            for encoding in ("utf-8", "gbk", "latin-1"):
                try:
                    return data.decode(encoding, errors="replace")
                except Exception:
                    continue
            return data.decode("utf-8", errors="replace")
        except serial.SerialException:
            return ""

    def _close_serial(self):
        """安全关闭串口"""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
                self._log("串口已关闭")
            except Exception:
                pass
        self.serial_conn = None

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def progress_step(self):
        """进度条前进一步"""
        self.root.after(0, lambda: self.progress.step(1))

    def _reset_ui(self):
        """恢复 UI 到初始状态"""
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.refresh_btn.configure(state=tk.NORMAL)

    def _on_close(self):
        """窗口关闭回调"""
        if self.upgrading:
            if not messagebox.askyesno("确认", "升级正在进行中，确定要退出吗？"):
                return
            self.upgrading = False
        self._close_serial()
        self.root.destroy()


# ======================================================================
def main():
    root = tk.Tk()
    app = SerialUpgradeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
