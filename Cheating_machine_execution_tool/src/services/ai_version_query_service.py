"""Explicit version requests: trusted capability jobs, factual output, one summary.

The conversation worker observes an admitted job even after model cancellation.
It never transfers the dialogue stop event to the business job or replays a job.
"""
import json
import re
import threading
import time

from src.models.ai_session_scope import session_scope
from src.services.ai_pc_conversation import PcConversationExecutor
from src.services.capability_jobs import TERMINAL
from src.services.ai_context_budget import context_capacity
from src.services.ai_context_usage import request_usage, reply_usage
from src.models.capabilities import CapabilityError


_NUMBERS = dict(zip("一二三四五六七八九十", range(1, 11)), 两=2,
                十一=11, 十二=12, 十三=13, 十四=14, 十五=15, 十六=16)
_FILLERS = ("请", "帮我", "麻烦", "给我", "顺序", "依次", "逐台", "查询", "查", "读取", "查看", "核对",
            "一下", "当前", "现在", "全部", "所有", "已选", "已勾选", "勾选", "样机", "设备", "光猫", "路由器",
            "的", "各", "分别", "是", "多少", "什么", "为", "台")
_FILLER = re.compile("|".join(sorted(_FILLERS, key=len, reverse=True)))


def version_available(owner):
    capability = getattr(owner, "capabilities", None)
    registry = getattr(getattr(capability, "service", None), "registry", None)
    if registry is None:
        return False
    try:
        registry.get("device.version")
    except CapabilityError:
        return False
    return True


def version_selection(text, current, targets):
    """Whitelist complete query expressions; unrelated/compound requests use AI."""
    compact = re.sub(r"[\s。？！?!]", "", text)
    if re.search("为什么|为何|是否|是不是|怎么|如何|不要|不能|上次|昨天|历史|日志|原因|假如|如果|然后|并且|同时|对比|分析", compact):
        return None
    remainder, count = re.subn(r"系统软件版本|内部软件版本|软件版本|系统版本|固件版本|版本信息|版本", "", compact)
    if not count:
        return None
    match = re.search(r"通道\d{1,2}(?:[、,，和及与](?:通道)?\d{1,2})*", remainder)
    explicit = [int(n) for n in re.findall(r"\d+", match[0])] if match else []
    if match:
        remainder = remainder[:match.start()] + remainder[match.end():]
    amount = re.search(r"(\d{1,2}|十[一二三四五六]?|[一二两三四五六七八九])台", remainder)
    wanted = None
    if amount:
        value = amount[1]
        wanted = int(value) if value.isdigit() else _NUMBERS[value]
        remainder = remainder[:amount.start()] + remainder[amount.end():]
    if _FILLER.sub("", remainder):
        return None
    available = [t.channel for t in targets]
    if explicit:
        channels = explicit
    elif wanted is not None or re.search("全部|所有|已选|勾选", compact):
        channels = available
    elif current and session_scope(current) == "batch":
        channels = [t["channel"] for t in current.get("batch_targets", [])]
    elif current and current.get("target"):
        channels = [current["target"]["channel"]]
    elif len(available) == 1:
        channels = available
    else:
        channels = []
    clarification = ""
    if (not channels or len(channels) != len(set(channels)) or any(c not in available for c in channels)
            or wanted is not None and wanted != len(channels)):
        clarification = "请明确本次查询的通道；当前有效目标为" + ("、".join("通道" + str(c) for c in available) or "暂无")
    return channels, clarification


def version_route(text, current, targets, fresh=False):
    selection = None if fresh else version_selection(text, current, targets)
    if selection is None:
        return None
    channels, clarification = selection
    return dict(intent="clarify" if clarification else "switch", scope="general" if clarification else
                "batch" if len(channels) > 1 else "device", channel=channels[0] if len(channels) == 1 and not clarification else None,
                channels=channels if len(channels) > 1 and not clarification else [], question=text,
                clarification=clarification, workflow="business")


def result_table(items):
    def cell(value):
        return str(value if value is not None else "未返回").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["| 通道 | 状态 | 软件版本 | 内部软件版本 | 编译时间 / 原因 |",
             "| --- | --- | --- | --- | --- |"]
    for item in items:
        success = item.get("status", "succeeded") == "succeeded"
        state = ("成功" if success else "未执行" if item.get("status") == "not_executed" else
                 "待核实" if item.get("status") == "unknown" else "失败")
        lines.append("| " + " | ".join(map(cell, (item["channel"], state,
            item.get("software_version", "未返回") if success else "—",
            item.get("internal_software_version", "未返回") if success else "—",
            item.get("onu_compile_time", "未返回") if success else item.get("error", "原因未返回")))) + " |")
    return "\n".join(lines)


class AiVersionQueryService:
    def __init__(self, owner):
        self.owner = owner
        self.restore_after = 0

    def _record(self, identifier, **changes):
        record = dict(self.owner.store.chat(identifier).get("version_query") or {})
        record.update(changes)
        self.owner.store.update_chat(identifier, version_query=record)
        return record

    def _message(self, identifier, job_id, suffix, text, role="assistant"):
        kind = "version:" + job_id + ":" + suffix
        if not any(item.get("kind") == kind for item in self.owner.store.chat_items(identifier)):
            self.owner.message(identifier, role, text, kind)

    def try_run(self, identifier, text, stop, profile, key):
        owner = self.owner
        capability = getattr(owner, "capabilities", None)
        session = owner.store.chat(identifier)
        if not version_available(owner) or session.get("diagnosis_only") or session.get("batch_parent"):
            return False
        selection = version_selection(text, session, tuple(owner.diagnostic.targets.values()))
        if selection is None or selection[1]:
            return False
        channels = selection[0]
        bound = [t["channel"] for t in session.get("batch_targets", [])]
        if not bound and session.get("target"):
            bound = [session["target"]["channel"]]
        if channels != bound:
            return False
        arguments = dict(channel_ids=channels)
        operation = capability._operation(identifier, "device.version", arguments)
        # Save the trusted operation association before admission. Recovery only looks up this operation.
        self._record(identifier, job_id="", operation_id=operation, channels=channels, state="submitting",
                     summary="pending", turn=session.get("capability_turn", ""))
        owner.emit(f"会话{identifier[:8]}版本快捷查询：通道={channels}；使用受控业务，不调用路由/执行模型")
        executor = PcConversationExecutor(stop, owner.diagnostic.emit)
        try:
            result = capability.execute(identifier, "query_device_version", arguments, stop, executor,
                lambda action: owner._review_action(identifier, action, profile, key, stop))
        except Exception:
            # A failed/uncertain admission is looked up by operation id, never retried.
            self._record(identifier, state="lookup_required")
            raise
        finally:
            executor.close()
        if not result.get("job_id"):
            authority = capability.authority(identifier, operation_id=operation)
            original = capability.service.jobs.find("device.version", authority)
            if original is None:
                self._record(identifier, state="not_admitted")
                owner.message(identifier, "system", "版本查询未准入：" + owner.redactor.dumps(result), "error")
                owner.store.update_chat(identifier, status="失败，可继续")
                return True
            result = original
        job_id = result["job_id"]
        self._record(identifier, job_id=job_id, state="waiting")
        owner.message(identifier, "system", f"版本查询业务已提交；任务{job_id[:8]}，等待逐台真实结果", "progress")
        authority = capability.authority(identifier, operation_id=operation)
        status = self._observe(identifier, job_id, authority)
        if not stop.is_set() and not owner.shutdown.is_set():
            self._summary(identifier, status, profile, key, stop)
        else:
            self._record(identifier, summary="skipped")
            owner.emit(f"会话{identifier[:8]}模型已停止；原版本任务{job_id[:8]}实际结果已保留，跳过AI说明")
        return True

    def _observe(self, identifier, job_id, authority):
        owner = self.owner
        cursor = 0
        observed = {}
        while True:
            status = owner.capabilities.service.jobs.status(job_id, authority, cursor)
            for event in status.get("events", []):
                cursor = max(cursor, event["event_id"])
                if event["stage"] == "version_item":
                    item = json.loads(event["message"])
                    observed[item["channel"]] = item
                    self._message(identifier, job_id, "channel:" + item["channel"], result_table([item]))
            if status["state"] in TERMINAL and len(status.get("events", [])) < 200:
                break
            time.sleep(.1)
        result = status.get("result") or {}
        observed.update({item["channel"]: item for item in result.get("items", [])})
        rows = list(observed.values())
        channels = (owner.store.chat(identifier).get("version_query") or {}).get("channels", [])
        present = {str(row["channel"]) for row in rows}
        for number in channels:
            if "channel_" + str(number) not in present:
                rows.append(dict(channel="channel_" + str(number), status="not_executed" if status["state"] != "unknown" else "unknown",
                                 error=result.get("error") or "原任务未返回该通道结果；未重新执行"))
        order = {"channel_" + str(n): i for i, n in enumerate(channels)}
        rows.sort(key=lambda item: order.get(item["channel"], len(order)))
        self._message(identifier, job_id, "result", f"版本查询结果（任务{job_id[:8]}，{status['state']}）\n\n" + result_table(rows))
        if not any(item["source"] == "版本查询/" + job_id for item in owner.store.chat_evidence(identifier)):
            owner.add_evidence(identifier, "版本查询/" + job_id, owner.redactor.dumps(dict(state=status["state"], items=rows)), "本次业务实际结果")
        self._record(identifier, state="completed")
        owner.store.update_chat(identifier, status="可继续" if status["state"] == "succeeded" else
                                "结果待核实" if status["state"] == "unknown" else "失败，可继续")
        owner.emit(f"会话{identifier[:8]}版本任务{job_id[:8]}结果投影完成：{status['state']}；通道={channels}")
        return dict(state=status["state"], items=rows)

    def _summary(self, identifier, result, profile, key, stop):
        owner = self.owner
        # Mark the attempt before the network request; restart cannot duplicate it.
        self._record(identifier, summary="attempted")
        client = None
        try:
            owner._profile(owner.store.chat(identifier))
            client = owner.diagnostic.client_factory(profile, key, owner.redactor)
            messages = [dict(role="system", content="仅解释给定版本查询结果，简短比较软件/内部版本差异。失败或未执行项不能推测版本。不得给出已验证之外的结论，不调用工具。"),
                        dict(role="user", content=owner.redactor.dumps(result))]
            usage = request_usage(profile, context_capacity(owner.store, profile),
                                  len(owner.redactor.dumps(messages).encode("utf-8")), 0)
            usage["request_kind"] = "version_summary"
            owner._save_usage(identifier, usage)
            owner.capabilities.service.metrics.model(identifier)
            owner.emit(f"会话{identifier[:8]}版本结果已显示；开始一次AI说明，仅发送本次结构化结果")
            reply = client.complete(messages, [], stop)
            usage = reply_usage(usage, reply.usage, profile.protocol, reply.history[len(messages):], owner.redactor.dumps)
            usage["request_kind"] = "version_summary"
            owner._save_usage(identifier, usage)
            if reply.calls:
                raise ValueError("版本说明不允许调用工具")
            if not stop.is_set() and reply.text:
                owner.message(identifier, "assistant", reply.text)
            self._record(identifier, summary="completed" if not stop.is_set() else "skipped")
        except Exception as exc:
            self._record(identifier, summary="failed")
            owner._fail_usage(identifier, "cancelled" if stop.is_set() else "failed")
            owner.message(identifier, "system", "版本查询真实结果已保留；AI说明未完成：" + owner.redactor.text(str(exc)), "error")
            owner.emit(f"会话{identifier[:8]}AI说明未完成；不重查设备、不改变真实查询结果")
        finally:
            if client is not None:
                client.close()

    def recover(self):
        """Read the original job after restart; never submit or regenerate explanations."""
        owner = self.owner
        if not getattr(owner, "capabilities", None) or time.monotonic() < self.restore_after or owner.shutdown.is_set():
            return
        self.restore_after = time.monotonic() + 1
        for session in owner.store.chats():
            record = session.get("version_query") or {}
            if record.get("state") not in ("submitting", "waiting", "lookup_required") or session["id"] in owner.running:
                continue
            identifier = session["id"]
            marker = threading.Event()
            with owner.lock:
                if identifier in owner.running:
                    continue
                owner.running[identifier] = marker
            try:
                authority = owner.capabilities.authority(identifier, operation_id=record["operation_id"])
                job = owner.capabilities.service.jobs.find("device.version", authority)
                if job is None:
                    self._record(identifier, state="not_found", summary="skipped")
                    owner.message(identifier, "system", "未找到原版本查询任务；没有重新执行，请核对原请求记录。", "error")
                else:
                    self._record(identifier, job_id=job["job_id"])
                    self._observe(identifier, job["job_id"], authority)
                    self._record(identifier, summary="skipped")
            except Exception as exc:
                self._record(identifier, state="recovery_unconfirmed", summary="skipped")
                owner.emit(f"会话{identifier[:8]}原版本任务状态未能确认；未重放：" + owner.redactor.text(str(exc)))
            finally:
                with owner.lock:
                    if owner.running.get(identifier) is marker:
                        owner.running.pop(identifier)
