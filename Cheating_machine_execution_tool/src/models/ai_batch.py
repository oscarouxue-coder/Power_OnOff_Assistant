"""多样机任务的阶段校验与真实结果投影，不从模型正文推断成功。"""
from dataclasses import dataclass


READ_ONLY_TOOLS = frozenset(("ask_user", "read_test_evidence", "read_pc_environment",
    "read_network_state", "read_serial_log", "read_serial_status", "read_local_file",
    "read_dut_state", "probe_connectivity"))
LABELS = {"pending": "未执行", "completed": "已取得证据", "reachable": "Ping可达",
          "unreachable": "Ping不通", "failed": "检查/执行失败", "unknown": "结果待核实",
          "waiting": "等待回复", "stopped": "已停止", "skipped": "跳过"}


@dataclass(frozen=True)
class BatchStage:
    scope: str
    select: str
    instruction: str
    read_only: bool = True
    probe: str = "none"

    @classmethod
    def parse(cls, value):
        if (not isinstance(value, dict) or set(value) != {"scope", "select", "instruction", "read_only", "probe"}
                or value["scope"] not in ("device", "pc")
                or value["select"] not in ("all", "failed", "remaining")
                or not isinstance(value["instruction"], str) or not 1 <= len(value["instruction"].strip()) <= 4000
                or type(value["read_only"]) is not bool or value["probe"] not in ("none", "wired", "wireless")
                or (value["scope"] == "pc" and value["probe"] != "none")):
            raise ValueError("批量任务阶段格式无效，未执行")
        return cls(**value)


def observed_status(results, actions=(), pending=False):
    if any(a["state"] in ("unknown", "executing") for a in actions):
        return "unknown"
    if pending:
        return "waiting"
    if any(a["state"] in ("failed", "blocked", "rejected", "cancelled") for a in actions):
        return "failed"
    probes = [r for name, r in results if name == "probe_connectivity" and isinstance(r, dict)]
    if probes:
        last = probes[-1]
        if "error" in last:
            return "failed"
        ok = (last.get("result") or {}).get("ok")
        if ok is None and "times_ms" in (last.get("result") or {}):
            ok = bool(last["result"]["times_ms"])
        if type(ok) is bool:
            return "reachable" if ok else "unreachable"
    if any(isinstance(r, dict) and "error" in r for _, r in results):
        return "failed"
    # 收到模型答复不是已执行的证据。
    return "completed" if results else "skipped"
