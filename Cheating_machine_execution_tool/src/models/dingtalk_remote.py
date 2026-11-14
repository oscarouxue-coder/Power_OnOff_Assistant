"""钉钉入站消息与明确控制指令；模型文本不构成批准。"""
from dataclasses import dataclass
import re


BOT_TOPIC = "/v1.0/im/bot/messages/get"
HELP = ("发送“通道3 问题内容”开始排障，后续直接发送问题。\n"
        "指令：状态、通道 N、新会话、停止、批准 编号、拒绝 编号。\n"
        "只处理当前项目；会话按群成员和通道独立，默认帮我批准。")


@dataclass(frozen=True)
class RemoteMessage:
    id: str
    group: str
    corp: str
    sender: str
    nickname: str
    robot: str
    text: str
    webhook: str = ""
    expires: int = 0

    @classmethod
    def parse(cls, data):
        if (not isinstance(data, dict) or str(data.get("conversationType")) != "2"
                or data.get("isInAtList") is not True or data.get("msgtype") != "text"):
            raise ValueError("仅接收群内@机器人的文字消息")
        keys = ("msgId", "conversationId", "senderCorpId", "senderId", "robotCode")
        if any(not isinstance(data.get(k), str) or not 1 <= len(data[k]) <= 512 for k in keys):
            raise ValueError("消息缺少可信身份")
        text = data.get("text", {}).get("content", "")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 32768:
            raise ValueError("文字内容须为1至32768字符")
        expires = data.get("sessionWebhookExpiredTime", 0)
        return cls(*(data[k] for k in keys[:3]), data["senderId"],
                   str(data.get("senderNick", "群成员"))[:80], data["robotCode"], text.strip(),
                   str(data.get("sessionWebhook", "")), int(expires))


def command(text):
    text = text.strip()
    if text in ("帮助", "状态", "新会话", "停止"):
        return text, ""
    match = re.fullmatch(r"(批准|拒绝)\s+([A-Za-z0-9]{6,16})", text)
    if match:
        return match[1], match[2].upper()
    match = re.fullmatch(r"通道\s*(\d{1,4})(?:\s+([\s\S]*))?", text)
    if match:
        return "通道", (int(match[1]), (match[2] or "").strip())
    return "问题", text
