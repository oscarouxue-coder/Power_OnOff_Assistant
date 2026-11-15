"""飞书文字事件：保留可信身份，不从正文推断调用者或批准。"""
from dataclasses import dataclass
import json

from src.models.dingtalk_remote import command


HELP = ("直接描述问题；可说“改查通道3”“给通道3新建会话”或“只查本机电脑网络”。目标不明时会追问。\n"
        "指令：帮助、状态、通道 N、新会话、停止、批准 编号、拒绝 编号。\n"
        "仅处理当前项目；群聊、单聊、人员和目标独立，新会话默认完全访问，保留手动权限选择。切换后原任务继续，新排查按队列执行。")


@dataclass(frozen=True)
class FeishuMessage:
    id: str
    group: str
    corp: str
    sender: str
    nickname: str
    robot: str
    text: str
    chat_type: str
    generation: int = 0

    @classmethod
    def parse(cls, data, app_id, bot_id):
        try:
            header, event = data["header"], data["event"]
            sender, message = event["sender"], event["message"]
            if (header["event_type"] != "im.message.receive_v1" or header["app_id"] != app_id
                    or sender["sender_type"] != "user" or message["message_type"] != "text"
                    or message["chat_type"] not in ("group", "p2p")
                    or sender["tenant_key"] != header["tenant_key"]):
                raise ValueError
            identities = (message["message_id"], message["chat_id"], header["tenant_key"],
                          sender["sender_id"]["open_id"], app_id)
            if any(not isinstance(value, str) or not 1 <= len(value) <= 512 for value in identities):
                raise ValueError
            text = json.loads(message["content"])["text"]
            if not isinstance(text, str):
                raise ValueError
            if message["chat_type"] == "group":
                mentions = [item for item in message.get("mentions", [])
                            if item.get("id", {}).get("open_id") == bot_id and bot_id]
                if not mentions:
                    raise ValueError
                for item in mentions:
                    key = item.get("key")
                    if not isinstance(key, str) or not key:
                        raise ValueError
                    text = text.replace(key, "")
            text = text.strip()
            if not 1 <= len(text) <= 32768:
                raise ValueError
            identifier, chat, tenant, user, app = identities
            return cls(identifier, chat, tenant, user, "成员" + user[-8:], app, text, message["chat_type"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("仅接收本应用企业内用户的单聊文字或群内@本机器人的文字") from None
