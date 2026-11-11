"""有限工具注册表；模型只能选操作，不能提交设备命令、路径或 Shell。"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import threading
import time
import uuid

from line_check_assistant.subprocess_window import hidden_window_kwargs
from src.core.ai_debug_transport import DiagnosticTransport, DebugConnectionUnavailable
from src.utils.ai_output import decode_pc_output


READ_COMMANDS = {
    "system": "uname -a; cat /proc/uptime; cat /proc/version; cat /etc/openwrt_release 2>/dev/null",
    "network": "ip -s link; ip -4 addr; ip route; cat /proc/net/arp",
    "wifi": "iw dev; iwinfo 2>/dev/null",
    "logs": "logread 2>/dev/null | tail -n 120; dmesg | tail -n 80",
}


def tool_schemas(deep=False):
    tools = [
        {"name": "read_pc_environment", "description": "读取PC系统、权限、网卡/IP/路由及当前无线接口状态，不修改网络。", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "read_serial_log", "description": "被动读取本次目标已打开串口的近期输出，不发送命令。", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "read_dut_state", "description": "Telnet优先、串口回退读取目标DUT状态。", "parameters": {"type": "object", "properties": {"category": {"type": "string", "enum": list(READ_COMMANDS)}}, "required": ["category"], "additionalProperties": False}},
    ]
    if deep:
        for name, description in (("capture_packets", "在已有tcpdump上进行最多30秒、256包、96字节截断的有界抓包，保存原始文件到本地，只向AI返回摘要。"),
                                  ("follow_logs", "最多30秒跟踪系统日志，任务结束只停止本次进程。"),
                                  ("kernel_debug", "仅已验证OpenWrt临时提高内核console日志级别，30秒后恢复原级别。")):
            tools.append({"name": name, "description": description,
                          "parameters": {"type": "object", "properties": {}, "additionalProperties": False}})
    return tools


class DiagnosticToolExecutor:
    def __init__(self, target, stop, emit, store, redactor, serial_acquire, serial_read,
                 busy=lambda _target: False, transport_factory=DiagnosticTransport):
        self.target, self.stop, self.emit, self.store, self.redactor = target, stop, emit, store, redactor
        self.serial_acquire, self.serial_read, self.busy = serial_acquire, serial_read, busy
        self.transport_factory = transport_factory
        self.transport = None
        self.allow_read_fallback = True
        self.used = 0
        self.recovery_state = "无临时修改"

    def _connection(self):
        if self.transport is None:
            self.transport = self.transport_factory(self.target, self.stop, self.emit,
                                                    self.serial_acquire, self.busy)
            try:
                self.transport.open()
            except Exception:
                self.transport.close()
                self.transport = None
                raise
            self._recover_pending()
        return self.transport

    def execute(self, name, arguments, deep=False):
        if self.stop.is_set():
            raise InterruptedError("诊断已取消")
        self.used += 1
        if self.used > 10:
            return {"error": "已达到10次采集上限"}
        allowed = {item["name"]: item for item in tool_schemas(deep)}
        try:
            params = json.loads(arguments) if isinstance(arguments, str) else arguments
            if name not in allowed or not isinstance(params, dict):
                raise ValueError("未知工具或参数格式")
            if name == "read_dut_state":
                if set(params) != {"category"} or params["category"] not in READ_COMMANDS:
                    raise ValueError("不允许的DUT查询类别")
            elif params:
                raise ValueError("工具不接受额外参数")
            self.emit(f"[AI采集] 开始：{name}，通道{self.target.channel}")
            if name == "read_pc_environment":
                result = self.pc_environment()
            elif name == "read_serial_log":
                result = self.serial_read(self.target)
            elif name == "read_dut_state":
                connection = self._connection()
                try:
                    result = connection.command(READ_COMMANDS[params["category"]])
                except DebugConnectionUnavailable as exc:
                    if connection.kind != "Telnet":
                        raise
                    if not self.allow_read_fallback:
                        connection.close()
                        self.transport = None
                        raise DebugConnectionUnavailable(
                            f"{exc}；未自动切换通道或重新登录，请重新请求查询并确认新连接") from exc
                    self.emit("[AI Debug] Telnet只读查询连接失效，回退串口核查；临时修改不自动重发")
                    connection.fallback_serial()
                    result = connection.command(READ_COMMANDS[params["category"]])
            else:
                result = self._temporary(name)
            self.emit(f"[AI采集] 完成：{name}")
            return {"tool": name, "evidence": self.redactor.text(str(result))[:65536]}
        except InterruptedError:
            raise
        except Exception as exc:
            self.emit(f"[AI采集] 跳过/失败：{name}；{self.redactor.text(str(exc))}")
            return {"tool": name, "error": self.redactor.text(str(exc))}

    def pc_environment(self):
        info = {"system": platform.platform(), "python": platform.python_version(),
                "channel": self.target.channel, "vlan": self.target.vlan,
                "configured_source": self.target.bind_ip, "configured_dut": self.target.host,
                "configured_com": self.target.port, "configured_subnet_mask": self.target.subnet_mask,
                "captured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            network = ipaddress.ip_network(self.target.bind_ip + "/" + self.target.subnet_mask, strict=False)
            info["configured_same_subnet"] = ipaddress.ip_address(self.target.host) in network
        except ValueError:
            info["configured_same_subnet"] = "无法根据配置确认"
        if os.name == "nt":
            import ctypes
            info["administrator"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
            for args in (["ipconfig", "/all"], ["route", "print", "-4"], ["netsh", "wlan", "show", "interfaces"]):
                if self.stop.is_set():
                    break
                self.emit("[AI采集] PC TX：" + " ".join(args))
                result = subprocess.run(args, capture_output=True, timeout=20, **hidden_window_kwargs())
                text, encoding = decode_pc_output(result.stdout)
                info[" ".join(args)] = text[:65536]
                status = "成功" if result.returncode == 0 else "失败"
                self.emit(f"[AI采集] PC RX：{' '.join(args)}；{status}；返回码={result.returncode}；编码={encoding}"
                          + ("；存在无法解码的字节" if encoding.endswith("/replace") else ""))
        return self.redactor.dumps(info)

    def _temporary(self, name):
        connection = self._connection()
        self._recover_pending()
        identifier = uuid.uuid4().hex
        path = "/tmp/lca_" + identifier
        record = {"channel": self.target.channel, "host": self.target.host,
                  "port": self.target.port, "operation": name, "path": path}
        # 连接不明/断线恢复记录必须先落盘；记录中没有设备凭据。
        self.store.recovery(identifier, record)
        self.recovery_state = "恢复待完成"
        try:
            if name == "kernel_debug":
                current = connection.command("test -f /etc/openwrt_release && cat /proc/sys/kernel/printk")
                match = re.search(r"(?m)^([0-8])\s+[0-8]\s+[0-8]\s+[0-8]\s*$", current)
                if not match:
                    raise RuntimeError("不支持的设备或无法确认原日志级别，跳过临时修改")
                record["old_level"] = match[1]
                self.store.recovery(identifier, record)
                connection.command("dmesg -n 8")
            else:
                command = (f"tcpdump -p -n -i any -s 96 -c 256 -w {path}.pcap >{path}.out 2>&1"
                           if name == "capture_packets" else f"logread -f >{path}.out 2>&1")
                tool = "tcpdump" if name == "capture_packets" else "logread"
                check = connection.command(f"command -v {tool}")
                if not re.search(r"(?m)^/[^\r\n ]*/" + tool + r"\s*$", check):
                    raise RuntimeError(f"DUT没有可确认的{tool}，不安装工具")
                # ulimit是子Shell局部限制；日志文件最大约1MiB，不影响DUT原进程。
                launched = connection.command(f"(ulimit -f 2048; exec {command}) & echo __LCA_PID:$!")
                pid = re.search(r"(?m)^__LCA_PID:(\d+)\s*$", launched)
                if pid:
                    record["pid"] = pid[1]
                    self.store.recovery(identifier, record)
            self.stop.wait(30)
        finally:
            self._restore(identifier, record)
            if name != "kernel_debug" and self.recovery_state != "恢复待完成":
                self.store.recovery(identifier, dict(record, files_only=True))
                self.recovery_state = "采集进程已停止，临时文件待归档/清理"
        if self.recovery_state == "恢复待完成":
            if self.stop.is_set():
                raise InterruptedError("已取消，临时操作恢复待完成")
            raise RuntimeError("临时操作恢复待完成，停止深入采集并保留恢复记录")
        if self.stop.is_set():
            self._remove_files(identifier, record)
            raise InterruptedError("已停止采集并完成可执行的恢复")
        if name == "capture_packets":
            raw = connection.command(f"echo __LCA_DATA_BEGIN; base64 {path}.pcap; echo __LCA_DATA_END")
            match = re.search(r"(?m)^__LCA_DATA_BEGIN\r?\n([A-Za-z0-9+/=\r\n]+)^__LCA_DATA_END", raw, re.M)
            if not match:
                raise RuntimeError("原始抓包读取失败；未将原始抓包发送模型")
            binary = base64.b64decode(re.sub(r"\s", "", match[1]), validate=True)
            if len(binary) > 10 * 1024 * 1024:
                raise RuntimeError("抓包超过10MiB上限")
            directory = self.store.directory / "captures"
            directory.mkdir(exist_ok=True)
            (directory / (identifier + ".pcap")).write_bytes(binary)
            result = connection.command(f"tcpdump -nn -r {path}.pcap -c 40 2>&1")
            self.emit(f"[AI采集] 原始抓包已保存：{directory / (identifier + '.pcap')}")
        elif name == "follow_logs":
            result = connection.command(f"tail -n 160 {path}.out")
        else:
            result = connection.command("dmesg | tail -n 100")
        self._remove_files(identifier, record)
        return result

    def _remove_files(self, identifier, record):
        if record["operation"] == "kernel_debug":
            return
        path = record["path"]
        if not re.fullmatch(r"/tmp/lca_[a-f0-9]{32}", path):
            return
        try:
            self.transport.command(f"rm -f {path}.pcap {path}.out", cleanup=True)
            self.store.recovery(identifier, record, "restored")
            self.recovery_state = "已恢复，临时文件已清理"
        except Exception:
            self.emit("[AI采集] 本次临时输出文件清理待完成")
            record = dict(record, files_only=True)
            self.store.recovery(identifier, record)
            self.recovery_state = "恢复待完成"

    def _restore(self, identifier, record):
        try:
            connection = self.transport
            if record["operation"] == "kernel_debug":
                old = record.get("old_level")
                if old is not None and re.fullmatch(r"[0-8]", old):
                    connection.command("dmesg -n " + old, cleanup=True)
                    result = connection.command("cat /proc/sys/kernel/printk", cleanup=True)
                    if not re.search(r"(?m)^" + old + r"\s+[0-8]\s+[0-8]\s+[0-8]\s*$", result):
                        raise RuntimeError("原日志级别恢复未确认")
            else:
                path = record["path"]
                if not re.fullmatch(r"/tmp/lca_[a-f0-9]{32}", path):
                    raise ValueError("恢复记录路径无效")
                # 重定向文件不出现在logread的argv中，必须核对进程名及stdout文件。
                # 只停止本任务的输出文件持有者；不结束shell/grep或其它logread。
                executable = "tcpdump" if record["operation"] == "capture_packets" else "logread"
                matcher = ("for p in /proc/[0-9]*/cmdline; do n=${p#/proc/}; n=${n%/cmdline}; "
                           f"[ \"$(cat /proc/$n/comm 2>/dev/null)\" = '{executable}' ] || continue; "
                           f"[ \"$(readlink /proc/$n/fd/1 2>/dev/null)\" = '{path}.out' ] || continue; ")
                command = ("sleep 1; " + matcher + "kill -TERM \"$n\" 2>/dev/null; done; sleep 1; " +
                           matcher + "echo __LCA_REMAINING; done; echo __LCA_STOPPED")
                result = connection.command(command, cleanup=True)
                if re.search(r"(?m)^__LCA_REMAINING\s*$", result) or not re.search(r"(?m)^__LCA_STOPPED\s*$", result):
                    raise RuntimeError("采集进程停止未确认")
            self.store.recovery(identifier, record, "restored")
            self.recovery_state = "已恢复/已停止本次采集进程"
            self.emit("[AI采集] 临时操作已恢复：" + record["operation"])
        except Exception:
            self.recovery_state = "恢复待完成"
            self.emit("[AI采集] 恢复待完成；下次连接核查，禁止通过重启恢复")

    def _recover_pending(self):
        for identifier, record in self.store.pending_recovery():
            if (record.get("channel"), record.get("host"), record.get("port")) == (
                    self.target.channel, self.target.host, self.target.port):
                self._restore(identifier, record)
                if self.recovery_state != "恢复待完成" and record.get("files_only"):
                    self._remove_files(identifier, record)
                if self.recovery_state == "恢复待完成":
                    raise RuntimeError("存在未恢复的临时操作，请先核查")

    def close(self):
        if self.transport:
            self.transport.close()
