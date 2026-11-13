"""完整工具的请求校验、不可变操作摘要与授权指纹。"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


ACTION_TOOLS = ("run_local_command", "read_local_file", "write_local_file", "run_dut_command", "read_serial_status")
OUTPUT_LIMIT = 1024 * 1024


@dataclass(frozen=True)
class ActionAssessment:
    risk: str
    reason: str

    @classmethod
    def parse(cls, text):
        value = json.loads(text)
        if (not isinstance(value, dict) or set(value) != {"risk", "reason"}
                or value["risk"] not in ("ordinary", "dangerous", "unknown", "blocked")
                or not isinstance(value["reason"], str) or not 1 <= len(value["reason"].strip()) <= 2000):
            raise ValueError("风险审查返回格式无效")
        return cls(value["risk"], value["reason"].strip())


def action_fingerprint(action):
    fields = {k: action[k] for k in ("id", "session_id", "run_id", "target", "profile", "name", "params", "before")}
    fields.update({key: action[key] for key in ("permission_mode", "authorization_id", "authorization_source") if key in action})
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def normalize_action(name, params):
    if name not in ACTION_TOOLS or not isinstance(params, dict):
        raise ValueError("未知操作或参数无效")
    required, optional = {
        "run_local_command": ({"command"}, {"cwd", "timeout_seconds"}),
        "run_dut_command": ({"command"}, {"timeout_seconds"}),
        "read_local_file": ({"path"}, {"offset_bytes", "max_bytes"}),
        "write_local_file": ({"path", "content"}, set()),
        "read_serial_status": (set(), set()),
    }[name]
    if not required <= set(params) or set(params) - required - optional:
        raise ValueError("工具参数不匹配")
    result = dict(params)
    for key in required:
        if not isinstance(result[key], str) or "\x00" in result[key]:
            raise ValueError("参数必须为不含NUL的文本")
        if key != "content" and not result[key].strip():
            raise ValueError("参数不能为空")
    if "command" in result and len(result["command"]) > 32768:
        raise ValueError("命令超过32768字符")
    if "content" in result and len(result["content"].encode("utf-8")) > OUTPUT_LIMIT:
        raise ValueError("单次文件写入超过1MiB；较大操作请分步执行")
    if "path" in result:
        result["path"] = str(Path(result["path"]).expanduser().resolve())
    if name == "run_local_command":
        cwd = result.get("cwd", str(Path.cwd()))
        if not isinstance(cwd, str) or not cwd.strip() or "\x00" in cwd:
            raise ValueError("工作目录无效")
        result["cwd"] = str(Path(cwd).expanduser().resolve())
    if "command" in result:
        value = result.setdefault("timeout_seconds", 60)
        if type(value) is not int or not 1 <= value <= 1800:
            raise ValueError("超时须为1至1800秒的整数")
    if name == "read_local_file":
        offset, limit = result.setdefault("offset_bytes", 0), result.setdefault("max_bytes", 65536)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= OUTPUT_LIMIT:
            raise ValueError("文件偏移或读取上限无效（最大1MiB）")
    return result


def action_tool_schemas():
    definitions = (
        ("run_local_command", "在本机当前Windows账号下执行PowerShell；按当前permission_mode审查/批准，不可绕过设备/串口占用保护。",
         {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800}}, ["command"]),
        ("read_local_file", "有界读取本机文件为文本，不执行文件内容；二进制请使用命令工具处理。",
         {"path": {"type": "string"}, "offset_bytes": {"type": "integer", "minimum": 0}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": OUTPUT_LIMIT}}, ["path"]),
        ("write_local_file", "写入UTF-8文本文件，覆盖前记录差异，按当前permission_mode审查/批准；父目录必须存在。",
         {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        ("run_dut_command", "向当前会话目标下发自定义Shell命令。复用锁源Telnet/共享串口；按当前permission_mode批准登录和操作，已下发命令不自动重试或切通道重发。",
         {"command": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800}}, ["command"]),
        ("read_serial_status", "只读查询当前目标COM的实际枚举、PnP故障代码、驱动和程序内部占用；不打开COM，外部占用者无证据时为未知。", {}, []),
    )
    return [{"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}
        for name, description, properties, required in definitions]
