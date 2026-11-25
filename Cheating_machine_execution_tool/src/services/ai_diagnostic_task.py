"""连续诊断的有界任务状态；不持有设备连接，不授予操作权限。"""
import hashlib
import json
import time
import uuid

from src.models.ai_batch import READ_ONLY_TOOLS


PLAN_TOOL = {
    "name": "update_diagnostic_plan",
    "description": "更新诊断检查步骤和带证据编号的观察笔记；笔记不代表根因已确认。",
    "parameters": {"type": "object", "properties": {
        "steps": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
            "required": ["text", "status"], "additionalProperties": False}},
        "findings": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
            "evidence_id": {"type": "string"}, "observation": {"type": "string"}},
            "required": ["evidence_id", "observation"], "additionalProperties": False}}},
        "required": ["steps", "findings"], "additionalProperties": False}}

TASK_INSTRUCTIONS = """
当前是连续诊断任务，仅定位原因并给出建议，不实施修复。
程序仅开放只读取证工具和update_diagnostic_plan。不得修改配置、执行自定义Shell、重启、升级、清日志或提高日志级别。
复杂问题先用update_diagnostic_plan列出简短检查步骤，取得证据后更新；简单问题直接回答，无需凑步骤。
根据实际结果调整方向，已经失败的相同查询不要反复尝试。工具失败仅表示取证限制，不代表DUT根因。
任务记忆的checks是实际取证记录；findings是模型观察笔记，仍须核对引用原文，不能自动当成已确认事实。
用户补充/纠正优先用于后续检查，不代表新的操作授权；未回答现场问题时不得猜测。
证据充分时直接总结；无新进展、取证受阻或预算结束时说明缺口并给建议，不为延长任务重复调用工具。
结论区分已观察事实、原因假设、无法确认项和建议；有实际证据才确认原因，不宣称已完成修复。
"""


class DiagnosticTask:
    max_rounds = 24
    max_calls = 48
    max_seconds = 600

    def __init__(self, question, saved=None, clock=time.monotonic):
        saved = saved or {}
        self.clock, self.started = clock, clock()
        self.rounds = self.calls = self.stalled = 0
        self.cache = {}
        self.results_seen = set()
        self.inputs = []
        self.input_ids = []
        self.turn_id = uuid.uuid4().hex
        self.pending_supplements = set()
        self.supplement_messages = {}
        self.unconfirmed_supplements = set()
        self.accepting = True
        self.boundaries = []
        self.memory = {"goal": saved.get("goal") or question[:4000],
                       "steps": saved.get("steps", []), "findings": saved.get("findings", []),
                       "checks": saved.get("checks", [])[-12:],
                       "corrections": saved.get("corrections", [])[-7:] + [question[:4000]],
                       "state": "处理中", "reason": ""}

    def snapshot(self):
        return dict(self.memory, rounds=self.rounds, calls=self.calls)

    def limit_reason(self):
        if self.rounds >= self.max_rounds:
            return "达到本次24轮诊断预算"
        if self.calls >= self.max_calls:
            return "达到本次48次工具预算"
        if self.clock() - self.started >= self.max_seconds:
            return "达到本次10分钟诊断预算"
        if self.stalled >= 3:
            return "连续三次检查没有新进展"
        return ""

    def supplement(self, text):
        if not self.accepting:
            raise ValueError("本次诊断正在收尾，请结束后继续发送")
        if len(self.inputs) >= 8 or sum(map(len, self.inputs)) + len(text) > 65536:
            raise ValueError("待处理补充过多，请等待下一次检查后再发送")
        identifier = uuid.uuid4().hex
        self.inputs.append(text)
        self.input_ids.append(identifier)
        self.pending_supplements.add(identifier)
        self.memory["corrections"] = (self.memory["corrections"] + [text[:4000]])[-8:]
        return identifier

    def take_inputs(self, *, with_ids=False):
        values, self.inputs = self.inputs, []
        identifiers, self.input_ids = self.input_ids, []
        if values:
            self.stalled = 0
            self.cache.clear()  # 用户纠正后允许一次重新核对当前状态。
            self.results_seen.clear()
        return list(zip(identifiers, values)) if with_ids else values

    @staticmethod
    def fingerprint(name, params):
        return hashlib.sha256(json.dumps([name, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def cached(self, name, params):
        item = self.cache.get(self.fingerprint(name, params))
        if item:
            self.stalled += 1
            return {"status": "相同检查本次已执行，跳过重复取证；可检索原始证据或改查其它方向",
                    "evidence_id": item["evidence_id"], "previous": item["summary"]}
        return None

    def record(self, name, params, result, evidence_id):
        failed = bool(result.get("error")) or result.get("status") in ("rejected_or_cancelled", "blocked", "unknown")
        nested = result.get("result", {})
        failed = failed or (isinstance(nested, dict) and bool(nested.get("error")))
        signature = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        empty_search = name == "read_test_evidence" and result.get("matched") == 0 and not result.get("history")
        self.stalled = self.stalled + 1 if failed or empty_search or signature in self.results_seen else 0
        self.results_seen.add(signature)
        summary = json.dumps(result, ensure_ascii=False)[:700]
        item = {"tool": name, "evidence_id": evidence_id, "failed": failed, "summary": summary}
        self.cache[self.fingerprint(name, params)] = item
        self.memory["checks"] = (self.memory["checks"] + [item])[-12:]

    def update_plan(self, params, evidence_ids):
        if not isinstance(params, dict) or set(params) != {"steps", "findings"}:
            raise ValueError("诊断计划参数无效")
        steps, findings = params["steps"], params["findings"]
        if not isinstance(steps, list) or not isinstance(findings, list) or len(steps) > 8 or len(findings) > 8:
            raise ValueError("诊断计划及观察笔记各最多8项")
        for step in steps:
            if (not isinstance(step, dict) or set(step) != {"text", "status"}
                    or step["status"] not in ("pending", "in_progress", "completed")
                    or not isinstance(step["text"], str) or not 1 <= len(step["text"]) <= 300):
                raise ValueError("诊断步骤格式无效")
        for finding in findings:
            if (not isinstance(finding, dict) or set(finding) != {"evidence_id", "observation"}
                    or not isinstance(finding["evidence_id"], str) or finding["evidence_id"] not in evidence_ids
                    or not isinstance(finding["observation"], str) or not 1 <= len(finding["observation"]) <= 500):
                raise ValueError("观察笔记须引用本会话已有证据，最多500字")
        changed = (steps, findings) != (self.memory["steps"], self.memory["findings"])
        self.stalled = 0 if changed else self.stalled + 1
        self.memory.update(steps=steps, findings=findings)
        return {"status": "诊断计划已更新", "note": "观察笔记仍须核对证据，未实施修复"}

    def compact(self, current):
        # 只在完整工具组之间裁剪请求；完整原始协议记录由会话层留存。
        if len(self.boundaries) <= 2:
            return current
        return [current[0]] + current[self.boundaries[-2]:]


def diagnostic_tools(tools):
    return [tool for tool in tools if tool["name"] in READ_ONLY_TOOLS] + [PLAN_TOOL]
