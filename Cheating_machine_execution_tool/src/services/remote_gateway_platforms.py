"""Optional platform adapters. Reuse existing SDK transports, parsing and reply formatting."""
from dataclasses import asdict
import json
import threading
import time

from src.models.dingtalk_remote import RemoteMessage
from src.models.feishu_remote import FeishuMessage
from src.models.remote_gateway import RemotePrincipal, canonical, digest
from src.services.remote_gateway_router import RemoteGatewayRouter


class GatewayPlatforms:
    def __init__(self, store, configs, *, emit=lambda line: None, senders=None):
        self.store, self.configs, self.emit = store, configs, emit
        self.router = RemoteGatewayRouter(store)
        self.senders = senders or {}
        self.transports, self.leases = [], []
        self.stop = threading.Event()
        self.worker = None
        with store.lock, store.db:
            store.db.execute("UPDATE replies SET state='unknown' WHERE state='sending'")

    def receive_dingtalk(self, data):
        message = RemoteMessage.parse(data)
        config = self.configs["dingtalk"]
        if not config.get("enabled") or (message.robot, message.corp, message.group) != (config["robot_code"], config["corp"], config["group"]):
            return
        principal = RemotePrincipal("dingtalk", message.robot, message.corp, "group", message.group, message.sender)
        self.receive(principal, message.id, message.text)

    def receive_feishu(self, data, bot_id):
        config = self.configs["feishu"]
        message = FeishuMessage.parse(data, config["app_id"], bot_id)
        allowed = (config.get("group_enabled") and message.chat_type == "group" and message.group == config["group"]
                   or config.get("p2p_enabled") and message.chat_type == "p2p")
        if not config.get("enabled") or not allowed or message.corp != config["corp"]:
            return
        self.receive(RemotePrincipal("feishu", message.robot, message.corp, message.chat_type, message.group, message.sender), message.id, message.text)

    def receive(self, principal, message_id, text):
        # Called by authenticated platform SDK callbacks only, never a public relay RPC.
        if self.stop.is_set():
            return
        try:
            response = self.router.handle(principal, message_id, text)
            if response["kind"] == "instances":
                content = "在线实例：\n" + ("\n".join(v["instance_id"][:8] + " | " + v["name"] for v in response["instances"]) or "暂无获准的在线实例")
            elif response["kind"] == "current":
                target = response["instance"]
                content = "当前实例：" + target["instance_id"][:8] + " | " + target["name"]
            elif response["kind"] == "request":
                target = response["request"]
                content = "实例：" + target["instance_id"][:8] + " | 请求：" + target["request_id"] + "\n已登记转发；尚未确认业务任务启动"
            else:
                content = json.dumps(response, ensure_ascii=False)
        except ValueError as exc:
            content = str(exc)
        self._queue(digest((principal.key, message_id)), principal, content)

    def _queue(self, reply_id, principal, text, instance_id="", run_id=""):
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO replies VALUES(?,?,?,?,?,'pending')",
                (reply_id, instance_id, run_id, canonical(asdict(principal)), text))

    def collect_results(self):
        with self.store.lock:
            rows = self.store.db.execute("SELECT request,instance,run,payload,correlation FROM messages WHERE correlation!='{}'").fetchall()
        for request_id, instance_id, run_id, payload, correlation in rows:
            receipt = json.loads(correlation)
            request = json.loads(payload)
            principal = RemotePrincipal.parse(request["principal"])
            if not any(v["instance_id"] == instance_id for v in self.store.instances(principal, online_only=False)):
                continue
            jobs = receipt.get("jobs", [])
            detail = "\n".join("任务：" + j["job_id"] + " | 通道：" + ",".join(map(str, j["channel_ids"])) + " | " + j["state"] +
                "\n" + json.dumps(j.get("result"), ensure_ascii=False) for j in jobs)
            text = "实例：" + instance_id[:8] + " | 启动：" + run_id[:8] + " | 请求：" + request_id + "\n"
            text += detail or receipt.get("notice", "实例已接收，尚未启动业务任务")
            if receipt.get("answer"):
                text += "\n" + receipt["answer"]
            self._queue(digest((request_id, receipt)), principal, text, instance_id, run_id)

    def send_one(self):
        with self.store.lock, self.store.db:
            row = self.store.db.execute("SELECT id,principal,payload,instance FROM replies WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                self.store.db.execute("UPDATE replies SET state='sending' WHERE id=?", (row[0],))
        if not row:
            return
        state = "unknown"
        try:
            principal = RemotePrincipal.parse(json.loads(row[1]))
            if row[3] and not any(v["instance_id"] == row[3] for v in self.store.instances(principal, online_only=False)):
                raise ValueError("结果发送前实例范围已经撤销")
            if principal.platform in self.senders:
                self.senders[principal.platform](principal, row[2], row[0])
            elif principal.platform == "dingtalk":
                from src.core.dingtalk_robot import send_text
                from src.services.dingtalk_remote_service import split_text
                config = self.configs["dingtalk"]
                if principal.chat != config["group"] or principal.corp != config["corp"]:
                    raise ValueError("回复聊天不属于绑定范围")
                for text in split_text(row[2]):
                    send_text(config["webhook"], config.get("secret", ""), text, at_all=False)
            else:
                from src.core.feishu_client import FeishuApi
                from src.services.feishu_output import reply_posts
                config = self.configs["feishu"]
                api = FeishuApi(config["app_id"], config["app_secret"])
                for index, post in enumerate(reply_posts(principal.chat, "LineCheckAssistant统一接入", row[2])):
                    api.send_post(principal.chat, post, identifier=digest((row[0], index))[:32])
            state = "sent"
        except Exception:
            self.emit("[统一网关] 平台回复未确认，记录unknown；不重新执行实例业务")
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE replies SET state=? WHERE id=?", (state, row[0]))

    def start(self):
        from src.core.dingtalk_stream import DingTalkStream, InstanceLease
        from src.core.feishu_stream import FeishuStream
        try:
            for platform, config in self.configs.items():
                if not config.get("enabled"):
                    continue
                if platform == "dingtalk":
                    lease = InstanceLease("client:" + config["client_id"])
                    transport = DingTalkStream(config["client_id"], config["client_secret"], self.receive_dingtalk, self.emit)
                else:
                    lease = InstanceLease("feishu:app:" + config["app_id"])
                    transport = FeishuStream(config["app_id"], config["app_secret"], self.receive_feishu, self.emit)
                lease.acquire()
                self.leases.append(lease)
                self.transports.append(transport)
                transport.start()
            self.worker = threading.Thread(target=self._loop, name="gateway-platform-replies", daemon=True)
            self.worker.start()
        except BaseException:
            self.close()
            raise

    def _loop(self):
        while not self.stop.wait(1):
            try:
                self.collect_results()
                self.send_one()
            except Exception:
                self.emit("[统一网关] 回复队列/持久化异常，请检查入口状态")

    def close(self):
        self.stop.set()
        for transport in self.transports:
            transport.begin_close()
        if self.worker:
            self.worker.join(12)
        deadline = time.monotonic() + 20
        while any(not transport.idle for transport in self.transports) and time.monotonic() < deadline:
            time.sleep(.05)
        if all(transport.idle for transport in self.transports):
            for lease in self.leases:
                lease.close()
        else:
            self.emit("[统一网关] 平台仍在收尾，保留应用互斥至进程退出")
