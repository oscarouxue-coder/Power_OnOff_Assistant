"""只解析已过滤批次/尝试的旧业务事件；凭据正文不会作为错误事件。"""
from __future__ import annotations

from dataclasses import replace
import re

from src.models.ai_diagnostics import DiagnosticEvent


class PowerDiagnosticEvents:
    def __init__(self):
        self.cycles = {}
        self.stages = {}
        self.attempts = {}

    def consume(self, run_id, message):
        kind = message.get("type")
        channel = int(message.get("channel") or 0)
        resume = str(message.get("attempt", 0))
        if kind == "diagnostic_event":
            return [DiagnosticEvent(run_id, channel, str(message["stage"]), str(message["status"]),
                str(message.get("detail", "")), int(message.get("cycle", 0)),
                str(message.get("event_id", "final")), str(message.get("band", "")),
                str(message.get("error_code", "")), str(message.get("feature", "power")))]
        if kind == "channel_started":
            self.cycles[channel] = int(message.get("completed", 0)) + 1
            self.stages.pop(channel, None)
            self.attempts[channel] = resume
            return []
        if kind in ("channel_result", "channel_ready"):
            stage, band, feature = self.stages.get(channel, ("power", "", "power"))
            status = "cancelled" if message.get("cancelled") else ("success" if message.get("ok") else "failed")
            return [DiagnosticEvent(run_id, channel, stage, status,
                    str(message.get("detail") or "通道最终结果"), self.cycles.get(channel, 1),
                    resume + ":final", band, feature=feature)]
        if kind != "log":
            return []
        text = str(message.get("message", ""))
        login = re.fullmatch(r"通道\s*(\d+)\s*第\s*(\d+)\s*次连接\s*telnet\s*失败，等待\s*\d+\s*s\s*再连接一次[；;]?", text.strip(), re.I)
        if login:
            channel = int(login[1])
            self.stages[channel] = "telnet_login", "", "telnet"
            return [DiagnosticEvent(run_id, channel, "telnet_login", "retry", text,
                    self.cycles.get(channel, 1), resume + ":" + login[2], feature="telnet")]
        if channel and re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}\s*登录成功", text.strip()):
            return [DiagnosticEvent(run_id, channel, "telnet_login", "success", text,
                    self.cycles.get(channel, 1), resume + ":login", feature="telnet")]
        wifi = re.fullmatch(r"\[WiFi测试\] 通道(\d+) 第(\d+)轮 (.*)", text, re.S)
        if wifi:
            channel, cycle, body = int(wifi[1]), int(wifi[2]), wifi[3]
            if body.startswith("WiFi信息："):
                return []
            if cycle < self.cycles.get(channel, 0):
                return []
            self.cycles[channel] = cycle
            body = re.sub(r"^\[[^\]]*\]\s*", "", body)
            band_match = re.match(r"(2\.4G|5G) (.*)", body, re.S)
            band = band_match[1] if band_match else self.stages.get(channel, ("wifi", "", "wifi"))[1]
            stage_text = band_match[2] if band_match else body
            # 原始 WiFi 信息只缓存，不解析为故障或工具请求。
            if stage_text.startswith(("SSID=", "SSID：", "SSID:")):
                return []
            stage = "wifi"
            feature = "wifi"
            if "Ping" in stage_text or "ping" in stage_text:
                stage, feature = "wifi_ping", "ping"
            self.stages[channel] = stage, band, feature
            attempt = re.match(r"第\s*(\d+)\s*/\s*4\s*次", stage_text)
            if attempt:
                self.attempts[channel, band] = attempt[1]
            status = None
            if stage_text.startswith(("取消", "跳过")):
                return []
            if stage_text.startswith(("成功：本项无线测试通过", "成功：已连接")):
                status = "success"
            elif re.match(r"第\s*\d+\s*/\s*4\s*次(?:未通过：|扫描失败：|未连接，)", stage_text):
                status = "error"
            elif stage_text.startswith(("测试环境异常：", "验证失败：", "获取WiFi信息失败", "失败：")):
                status = "error"  # 最终失败仅以 channel_result 为准。
            if not status:
                return []
            code = re.search(r"(?:错误码|原因码|WinError)[=：: ]+([0-9A-Fa-fx]+)", stage_text)
            return [DiagnosticEvent(run_id, channel, stage, status, stage_text, cycle,
                    resume + ":" + self.attempts.get((channel, band), "1"), band,
                    code[1] if code else "", feature)]
        start = re.fullmatch(r"\*+\s*通道\s*【(\d+)】\s*开始第\s*(\d+)\s*次测试\s*\*+", text.strip())
        if start:
            self.cycles[int(start[1])] = int(start[2])
            return []
        normal = re.search(r"通道(\d+)下挂的设备在第(\d+)次测试时正常$", text)
        if normal:
            channel = int(normal[1])
            return [DiagnosticEvent(run_id, channel, "power", "success", text, int(normal[2]), resume, feature="power")]
        retry = re.fullmatch(r"通道\s*(\d+)\s*执行指令：\s*(.+?)，在第\s*(\d+)\s*次时出现错误；准备第\s*\d+\s*/\s*\d+\s*次验证", text.strip())
        if retry:
            channel = int(retry[1])
            # 相同命令为同一阶段；命令正文仅作证据，不可成为可执行工具参数。
            stage = "command:" + retry[2]
            self.stages[channel] = stage, "", "telnet"
            return [DiagnosticEvent(run_id, channel, stage, "retry", text,
                    self.cycles.get(channel, 1), resume + ":" + retry[3], feature="telnet")]
        return []
