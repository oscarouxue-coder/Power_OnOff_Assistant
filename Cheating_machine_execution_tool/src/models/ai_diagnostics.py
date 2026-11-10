"""AI 诊断边界；不包含凭据、设备命令或 UI 对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid


PROVIDERS = {
    "DeepSeek": ("https://api.deepseek.com", "chat_completions"),
    "MiniMax": ("https://api.minimax.io/v1", "chat_completions"),
    "OpenAI": ("https://api.openai.com/v1", "responses"),
    "自定义": ("", "chat_completions"),
}


@dataclass(frozen=True)
class ProviderProfile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "新接入配置"
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    protocol: str = "chat_completions"
    model: str = ""
    timeout: int = 60
    max_output: int = 4096
    capability: str = "未验证"
    # 只有经过该配置本次测试的能力才能启用工具；更改配置会清除此字段。
    tested_fingerprint: str = ""
    credential_revision: str = ""


@dataclass(frozen=True)
class DiagnosticTarget:
    channel: int
    vlan: str
    port: str
    bind_ip: str
    host: str
    telnet_port: int = 23
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    user_prompt: str = "ogin:"
    password_prompt: str = "Password:"
    shell_prompt: str = "#"
    no_auth: bool = False
    subnet_mask: str = "255.255.255.0"


@dataclass(frozen=True)
class DebugTriggerPolicy:
    channels: tuple[int, ...] = ()
    features: tuple[str, ...] = ("power", "telnet", "wifi", "ping")
    threshold: int = 3
    cooldown: int = 60
    keywords: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()
    deep_enabled: bool = True


@dataclass(frozen=True)
class DiagnosticEvent:
    run_id: str
    channel: int
    stage: str
    status: str
    detail: str
    cycle: int = 0
    attempt: str = ""
    band: str = ""
    error_code: str = ""
    feature: str = "power"
    trusted: bool = True


@dataclass(frozen=True)
class TriggerDecision:
    event: DiagnosticEvent
    level: str
    reason: str


@dataclass
class ModelReply:
    text: str
    calls: list[dict[str, Any]]
    history: list[dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagnosticJob:
    id: str
    profile: ProviderProfile
    target: DiagnosticTarget
    question: str
    run_id: str
    level: str = "light"
    evidence: str = ""
    event: DiagnosticEvent | None = None
