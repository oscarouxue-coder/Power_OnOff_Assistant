# -*- coding: utf-8 -*-
"""Build standalone HTML/SVG/CSV observations; no plotting/runtime dependencies."""
import argparse
import csv
import html
import io
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MIB = 1024 * 1024


def logging_probes():
    from src.core.serial_transport import PySerialSession
    from src.core.telnet_transport import TelnetSession
    from src.models.serial_models import SerialSettings
    from src.core.transport_observation import HistoryRegistry
    values = {}
    session = PySerialSession(SerialSettings("SIM_PROBE_ONLY"))
    session._log_handle = io.StringIO()
    original = "\u4e2d\u6587"
    raw = original.encode("utf-8")+b"\r\n"
    for part in (raw[:1], raw[1:]): session._emit("RX", part, session._display(part))
    saved = session._log_handle.getvalue()
    values["utf8_split"] = {"input_bytes": len(raw), "original_text_preserved": original in saved,
                            "replacement_present": "\ufffd" in saved, "byte_fidelity_passed": False}
    session = PySerialSession(SerialSettings("SIM_PROBE_ONLY"))
    session._log_handle = io.StringIO()
    session._emit("RX", b"x"*(1024*1024), "x"*(1024*1024))
    values["no_newline"] = {"offered_to_line_writer_bytes": 1024*1024,
                            "pending_chars": len(session._rx_log_line_buffer) + session._rx_line_spilled,
                            "resident_chars": len(session._rx_log_line_buffer),
                            "spilled_chars": session._rx_line_spilled,
                            "written_chars_before_close": len(session._log_handle.getvalue()),
                            "note": "Line-writer-only probe; no physical driver. Long tails spill until a flush boundary."}
    session._flush_pending_rx_log_line()
    values["no_newline"]["written_chars_after_explicit_tail_flush"] = len(session._log_handle.getvalue())

    class FailingLog:
        def write(self, _): raise OSError(28, "synthetic disk full")
        def flush(self): pass
        def close(self): pass
    class Driver:
        in_waiting = 7
        def read(self, _): return b"sample\n"
        def close(self): pass
        def cancel_read(self): pass
    session = PySerialSession(SerialSettings("SIM_PROBE_ONLY"))
    session._serial = Driver(); session._log_handle = FailingLog()
    escaped = []
    def reader():
        try: session._reader_loop()
        except Exception as exc: escaped.append(type(exc).__name__)
    session._reader = threading.Thread(target=reader, name="sim-write-failure")
    session._reader.start(); session._reader.join(2)
    observation = HistoryRegistry.inspect(session, {"session_id": "probe", "protocol": "serial", "endpoint": "SIM_PROBE_ONLY"})
    values["serial_disk_failure"] = {"escaped_reader_loop_exception": escaped,
        "reader_stopped": not session._reader.is_alive(), "history_bytes": len(session._history),
        "receive_error_recorded": session.error is not None, "observed_write_status": observation["write_status"],
        "exact_writer_error_available_to_monitor": observation["write_error"] is not None,
        "note": "Read-only monitor detects stopped acquisition; it does not repair the original writer or recover the lost line."}
    try: session.close()
    except (OSError, RuntimeError): pass
    telnet = TelnetSession.__new__(TelnetSession)
    telnet._log_handle = FailingLog()
    raised = False
    try: telnet._emit(b"RX", b"sample\n")
    except OSError: raised = True
    values["telnet_disk_failure"] = {"writer_error_escaped_emit": raised,
        "existing_error_suppressed": not raised, "note": "No socket created. Exact suppressed writer error cannot be obtained by read-only sampling."}
    return values


def linear_rate(points):
    points = [(x,y) for x,y in points if y is not None]
    if len(points) < 2: raise ValueError("Insufficient observed samples for a growth estimate")
    mx = sum(x for x, _ in points)/len(points)
    my = sum(y for _, y in points)/len(points)
    denominator = sum((x-mx)**2 for x, _ in points)
    return sum((x-mx)*(y-my) for x, y in points)/denominator if denominator else 0.0


def live_history(row):
    active = [item for item in row["sessions"] if not item.get("final")]
    if row.get("registry_busy") or any(item.get("sample_status") != "ok" for item in active):
        return None
    return sum(item["history_bytes"] for item in active)


def channel_history(row, channel):
    for item in row["sessions"]:
        if item.get("channel") == channel and not item.get("final"):
            return item.get("history_bytes")
    return 0 if row.get("stage") == "after_release" and not row.get("registry_busy") else None


def svg_chart(path, title, series, y_label):
    width, height = 1040, 400
    left, top, right, bottom = 85, 42, 25, 70
    all_points = [p for _, points in series for p in points if p[1] is not None]
    xmax = max((x for x, _ in all_points), default=1) or 1
    ymax = max((y for _, y in all_points), default=1)*1.08 or 1
    palette = ["#1267a6", "#d66a12", "#168351", "#ba375b", "#7952aa", "#8b652e", "#18909b", "#565f7d", "#3b8edb", "#e5a32d", "#63a84f", "#d56786", "#a286d0", "#aa8964", "#56bdc1", "#9aa4b6"]
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><g font-family="Arial,sans-serif" font-size="13" fill="#23313b">',
              f'<text x="{left}" y="24" font-size="18">{html.escape(title)}</text>']
    for n in range(5):
        fraction = n/4
        x = left+fraction*(width-left-right); y = height-bottom-fraction*(height-top-bottom)
        chunks.append(f'<path d="M{left},{y}H{width-right}" stroke="#e1e7ec"/><text x="{left-10}" y="{y+4}" text-anchor="end">{ymax*fraction:.1f}</text>')
        chunks.append(f'<text x="{x}" y="{height-bottom+22}" text-anchor="middle">{xmax*fraction:.1f}</text>')
    for index, (label, points) in enumerate(series):
        color = palette[index % len(palette)]
        coords = " ".join(f'{left+x/xmax*(width-left-right):.2f},{height-bottom-y/ymax*(height-top-bottom):.2f}' for x, y in points if y is not None)
        chunks.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
        chunks.append(f'<text x="{left+(index%8)*115}" y="{height-24+(index//8)*17}" fill="{color}">{html.escape(label)}</text>')
    chunks.append(f'<text x="{width//2}" y="{height-bottom+42}" text-anchor="middle">Elapsed minutes</text><text x="10" y="40">{html.escape(y_label)}</text></g></svg>')
    path.write_text("".join(chunks), encoding="utf-8")


def build_report(directory, probes):
    summaries = []
    sections = []
    for channels in (8, 16):
        run = directory / f"channels{channels}"
        result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        samples = [json.loads(line) for line in (run / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
        live = [s for s in samples if s["stage"] in ("started", "running", "before_close")]
        fit = [s for s in live if s["elapsed_seconds"] >= 300] or live
        hr = linear_rate([(s["elapsed_seconds"], live_history(s)) for s in fit])
        rr = linear_rate([(s["elapsed_seconds"], s["rss_bytes"]) for s in fit])
        peak = max(s["rss_bytes"] for s in samples)
        total_history = sum(r["memory_history_bytes"] for r in result["rows"])
        # Older result files measured an unbounded history. Apply the configured ceiling
        # only when every channel in a real sample reported its resident-window limit.
        limits = [sum(row["history_limit_bytes"] for row in sample["sessions"])
                  for sample in live if len(sample["sessions"]) == channels
                  and all(row.get("history_limit_bytes") is not None for row in sample["sessions"])]
        resident_limit = max(limits) if limits else None
        summary = {"channels": channels, "elapsed_seconds": result["elapsed_seconds"], "samples": len(samples),
            "rss_start_bytes": samples[0]["rss_bytes"], "rss_peak_sampled_bytes": peak,
            "rss_after_release_bytes": samples[-1]["rss_bytes"], "history_before_release_bytes": total_history,
            "pending_rx_chars_peak_sampled": max(sum(i.get("pending_rx_chars", 0) for i in s["sessions"]) for s in samples),
            "history_bytes_per_second_ols": hr, "rss_bytes_per_second_ols": rr,
            "source_bytes": sum(r["source_bytes"] for r in result["rows"]),
            "received_bytes": sum(r["driver_received_bytes"] for r in result["rows"]),
            "disk_log_bytes": sum(r["disk_file_bytes"] for r in result["rows"]),
            "text_and_lifecycle_checks_passed": result["text_and_lifecycle_checks_passed"],
            "raw_byte_fidelity_accepted": False, "remaining_threads": result["remaining_threads"], "retained_sessions": result["retained_sessions"],
            "resident_history_limit_bytes": resident_limit,
            "history_spilled_bytes": (sum(r["history_spilled_bytes"] for r in result["rows"])
                                      if all("history_spilled_bytes" in r for r in result["rows"]) else None),
            "projections": [{"hours": hours, "history_gib": min(resident_limit if resident_limit is not None else float("inf"),
                                                                max(total_history, max(0,hr)*hours*3600))/(1024**3),
                             "rss_gib_linear_estimate": max(0,samples[0]["rss_bytes"]+max(0,rr)*hours*3600)/(1024**3),
                             "status": "trend_estimate_only_not_tested"} for hours in (72,168)]}
        summaries.append(summary)
        summary["unavailable_history_samples"] = sum(live_history(row) is None for row in live)
        summary["channel_history_mib_per_hour_ols"] = {str(c): linear_rate([(s["elapsed_seconds"],channel_history(s,c)) for s in fit])*3600/MIB for c in range(1,channels+1)}
        csvpath = run / "samples.csv"
        with csvpath.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["elapsed_seconds", "stage", "rss_bytes", "live_history_bytes", "pending_rx_chars", "disk_free_bytes"]+[f"channel_{c}_history_bytes" for c in range(1,channels+1)])
            for row in samples:
                indexed = {i.get("channel"): i for i in row["sessions"] if not i.get("final")}
                writer.writerow([row["elapsed_seconds"], row["stage"], row["rss_bytes"], live_history(row), sum(i.get("pending_rx_chars",0) for i in indexed.values()), row["disk_free_bytes"]]+[channel_history(row,c) for c in range(1,channels+1)])
        svg_chart(run/"rss_history.svg", f"{channels} channels: RSS and live RX history", [
            ("RSS", [(r["elapsed_seconds"]/60,r["rss_bytes"]/MIB) for r in samples]),
            ("Live history", [(r["elapsed_seconds"]/60,live_history(r)/MIB if live_history(r) is not None else None) for r in samples])], "MiB")
        channel_series = []
        for c in range(1,channels+1):
            points = [(r["elapsed_seconds"]/60, channel_history(r,c)/MIB if channel_history(r,c) is not None else None) for r in samples]
            channel_series.append((f"CH{c}",points))
        svg_chart(run/"channel_history.svg", f"{channels} channels: per-session RX history",channel_series,"MiB")
        rows = "".join(f'<tr><td>{r["channel"]}</td><td>{r["driver_received_bytes"]}</td><td>{r["memory_history_bytes"]}</td><td>{r.get("history_spilled_bytes", "—")}</td><td>{r["disk_file_bytes"]}</td><td>{r["records_on_disk"]}</td><td>{r["missing_records"]}</td><td>{r["duplicate_or_reordered_records"]}</td><td>{r["normalized_text_sha256_equal"]}</td></tr>' for r in result["rows"])
        projections = "".join(f'<li>{p["hours"]}h 趋势估算：history {p["history_gib"]:.2f} GiB；RSS {p["rss_gib_linear_estimate"]:.2f} GiB。未运行该时长。</li>' for p in summary["projections"])
        sections.append(f'<section><h2>{channels} 路 / {result["elapsed_seconds"]:.2f} 秒</h2><p>文本与资源收尾检查：{result["text_and_lifecycle_checks_passed"]}；字节保真验收：未通过/本格式不支持。样本 {len(samples)} 个，{result["sample_interval_seconds"]} 秒采样。</p><p>RSS 起始/采样峰值/释放后：{summary["rss_start_bytes"]/MIB:.2f} / {peak/MIB:.2f} / {summary["rss_after_release_bytes"]/MIB:.2f} MiB。历史 {total_history/MIB:.2f} MiB。历史增长 {hr*3600/MIB:.2f} MiB/h；RSS 线性拟合增长 {rr*3600/MIB:.2f} MiB/h。</p><img src="channels{channels}/rss_history.svg" alt="RSS and live history"><img src="channels{channels}/channel_history.svg" alt="Per-channel history"><ul>{projections}</ul><p>OLS 使用第5分钟之后的存活阶段样本；排除释放阶段。估算只适用于本次合成负载，不考虑后续内存不足、交换、输出速率变化或磁盘耗尽。</p><table><tr><th>通道</th><th>驱动实际接收 bytes</th><th>常驻原始历史 bytes</th><th>临时溢写 bytes</th><th>磁盘文本 bytes</th><th>记录数</th><th>缺失</th><th>重复/乱序</th><th>文本SHA256一致</th></tr>{rows}</table><p><a href="channels{channels}/samples.csv">CSV样本</a> · <a href="channels{channels}/result.json">完整结果</a> · <a href="channels{channels}/samples.jsonl">原始监测</a></p></section>')
    (directory/"summary.json").write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding="utf-8")
    body = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>A1/A2/A7 专项报告</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1120px;margin:36px auto;color:#24323d;padding:0 20px}h1,h2{color:#124f70}section{border-top:1px solid #d9e2e8;margin-top:32px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d9e2e8;padding:7px;text-align:right}img{width:100%;height:auto}pre{white-space:pre-wrap;background:#f0f4f7;padding:16px}.risk{background:#fff2d7;padding:16px}</style><h1>A1/A2/A7 真实专项验证报告</h1><p>模拟串口与隔离进程。输入数据和运行时长见各批次结果。</p><p class="risk">重要：接收原始字节、内存历史、带时间戳文本文件的大小不是同一个指标。ASCII 文本序号/内容校验通过不代表原始字节归档保真通过。input/*.rx.bin 是测试输入基准，不是程序新增的原始归档功能。</p><h2>负载及验证方法</h2><p>固定的可重现 OpenWrt 风格 ASCII 消息，10条/秒持续、100条/秒突发2秒/分钟、每5分钟空闲10秒；通道分相，部分CRLF跨读取块。每条含通道与序列号。使用当前 PySerialSession 和实际文件写入，无硬件；持续接收阶段保持同一会话。该负载尚未用现场设备数据校准。</p><p>输入文件、驱动读取与会话的完整原始历史分别按字节和 SHA256 对照；磁盘文本剥除程序时间戳与RX方向后，核对序列、条数和内容SHA256，并明确仅归一化CRLF。结束先停生产、排空驱动，再正常关闭并检查弱引用及线程。RSS不会因Python分配器而被要求立即回到启动值。表内峰值基于实际采样点。</p>'''
    body += "".join(sections)
    body += '<p>周期快照不是原子事务：驱动计数与各会话内存/文件采样有时差，期间的微小差额不能作为丢失判据；最终比较在停产、排空、关闭后进行。繁忙导致的未采到值保留空白并排除拟合，不当作零。各通道增长率见summary.json。</p><p>模拟驱动不执行波特率节流，100条/秒突发可能超过115200波特率实际线速，用于软件侧峰值压力；连续/空闲及日志类型接近常见OpenWrt形态，但未用现场DUT校准。72/168小时估算只代表此合成负载。</p>'
    body += '<section><h2>本轮日志异常与超长行探针</h2><pre>'+html.escape(json.dumps(probes,ensure_ascii=False,indent=2))+'</pre><p>串口写入错误会停止接收并向订阅方报告。无换行片段超过阈值时写入临时文件，直至遇到换行、其它日志事件或关闭。Telnet 的既有写入错误仍可能被抑制。具体观测值见以上探针。</p></section>'
    body += '<section><h2>A1/A2、兼容与风险</h2><p>A1/A2复现及相关自动化见 <a href="reproductions.json">旧版复现</a>、<a href="related_tests_final.txt">相关回归日志</a>。本机通用命令/写入保守拦截可能阻止无害命令；只读文件、证据检索、被动串口与材料分析保留，不未经确认放宽。</p><p>A2不能消除远端在发送检查之后瞬间重启的物理竞态；首次出现未识别提示会保守停止，厂商兼容须现场复验。不自动重发未知结果，清理失败仍保留恢复记录。</p><p>串口临时原始历史供当前会话持有者回看，持有者释放后自动清理。长期留存使用现有文本日志。实际运行时长见各批次结果。</p></section></html>'
    (directory/"REPORT.html").write_text(body,encoding="utf-8")
    return summaries


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--probe-only",action="store_true")
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    probes=logging_probes()
    (args.output/"logging_probes.json").write_text(json.dumps(probes,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.probe_only: print(json.dumps(probes,ensure_ascii=False)); return 0
    summaries=build_report(args.output,probes)
    print(json.dumps(summaries,ensure_ascii=False,indent=2))
    return 0 if all(s["text_and_lifecycle_checks_passed"] for s in summaries) else 1


if __name__=="__main__": sys.exit(main())
