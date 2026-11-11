"""对话排障的数据边界；授权只存在于进程内。"""
from dataclasses import dataclass, field
from datetime import datetime
import uuid


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    text: str
    kind: str = "text"
    created: str = field(default_factory=timestamp)


@dataclass(frozen=True)
class DiagnosticEvidence:
    source: str
    text: str
    run_id: str
    channel: int
    timing: str = "故障时/测试过程中记录"
    created: str = field(default_factory=timestamp)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


ASK_USER_TOOL = {
    "name": "ask_user",
    "description": "主动询问操作员无法自动确认的现场信息。说明原因与具体检查方式；只询问一个问题，未回答不得猜测。可先执行不依赖答案的检查，然后等待回复。",
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["question", "reason"], "additionalProperties": False},
}
