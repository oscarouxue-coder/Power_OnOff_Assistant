"""指定群的文字会话桥；复用现有排障/授权链路，不从模型文字批准操作。"""
from dataclasses import asdict
from src.services.ai_session_router import dispatch_remote
from src.models.ai_session_scope import target_channel, target_label, session_scope
import configparser
import hashlib
import json
import queue
import re
import secrets
import threading
import time

from src.core.dingtalk_robot import send_text
from src.core.ai_reply_cards import DingTalkReplyCard, CardStopped
from src.services.ai_reply_stream_service import ReplyStreamService
from src.utils.ai_redaction import hold_secret_prefix
from src.core.dingtalk_stream import DingTalkStream, InstanceLease, send_session_text, valid_session_url
from src.models.ai_actions import action_fingerprint
from src.models.ai_permissions import AUTO
from src.models.dingtalk_remote import HELP, RemoteMessage, command
from src.services.ai_store import profile_fingerprint
from src.services.dingtalk_remote_store import RemoteMailbox
from src.services.message_push_config_service import load_push_project_name


def split_text(text, byte_limit=1800):
    result, current, size = [], [], 0
    for char in text:
        width = len(char.encode("utf-8"))
        if current and size + width > byte_limit:
            result.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += width
    if current:
        result.append("".join(current))
    return result


class DingTalkRemoteService:
    def __init__(self, conversation, config_store, project_path, *, transport_factory=DingTalkStream,
                 lease_factory=InstanceLease, sender=send_text, session_sender=send_session_text,
                 clock=time.monotonic, autostart=True, send_interval=3.2, project_guarded=False):
        self.conversation, self.store = conversation, conversation.store
        self.config_store, self.project_path = config_store, project_path
        self.config = config_store.load()
        self.mailbox = RemoteMailbox(config_store.directory)
        self.transport_factory, self.lease_factory = transport_factory, lease_factory
        self.sender, self.session_sender, self.clock = sender, session_sender, clock
        self.send_interval = send_interval
        self.project_guarded = project_guarded
        self.lock = threading.RLock()
        self.transport, self.lease = None, None
        self.connection_status = "未启用"
        self.binding_code, self.binding_deadline, self.candidate = "", 0, None
        self.tokens, self.sessions, self.reply_context = {}, set(), {}
        self.sessions.update(s["id"] for s in self.store.chats() if (s.get("source") or {}).get("kind") == "dingtalk")
        self.local_only_approvals = set()
        self.stop_event = threading.Event()
        self.routing_generation = 0
        self.outbox = queue.Queue(maxsize=128)
        self.updates = conversation.subscribe()
        self.card_token_cache = {}
        self.reply_streams = ReplyStreamService(self.mailbox, self._stream_card, self._stream_allowed,
            self._sanitize, self._send_stream_final, self.emit, clock=self.clock)
        self.worker = threading.Thread(target=self._loop, name="dingtalk-ai", daemon=True)
        self.sender_thread = threading.Thread(target=self._send_loop, name="dingtalk-reply", daemon=True)
        if autostart:
            self.worker.start()
            self.sender_thread.start()

    def emit(self, text):
        self.conversation.emit("[钉钉接入] " + text)

    def status(self, text):
        with self.lock:
            changed = self.connection_status != text
            self.connection_status = text
        if changed:
            self.emit(text)

    def snapshot(self):
        with self.lock:
            return dict(status=self.connection_status, enabled=self.config["enabled"],
                        candidate=dict(self.candidate) if self.candidate else None,
                        binding=bool(self.binding_code and self.clock() < self.binding_deadline))

    def start(self):
        guard = getattr(self, "direct_admission", None)
        if guard is not None:
            guard("dingtalk", self.config)
        if self.stop_event.is_set():
            raise ValueError("接入服务正在退出")
        if self.transport is not None:
            if not self.transport.idle:
                return
            self.transport = None
            if self.lease:
                self.lease.close()
                self.lease = None
        if not all(self.config.get(k) for k in ("client_id", "client_secret", "robot_code")):
            raise ValueError("请先保存应用Client ID、Client Secret和Robot Code")
        identities = ["client:" + self.config["client_id"]]
        if not self.project_guarded:
            identities.append("project:" + str(self.config_store.directory.resolve()))
        self.lease = self.lease_factory(*identities)
        self.lease.acquire()
        try:
            self.transport = self.transport_factory(self.config["client_id"], self.config["client_secret"],
                                                    self.receive, self.status)
            self.transport.start()
        except Exception:
            self.lease.close()
            self.lease, self.transport = None, None
            raise

    def begin_binding(self):
        if self.config["enabled"]:
            raise ValueError("请先停用接入并等待当前排障清理，再重新绑定")
        self.start()
        with self.lock:
            self.binding_code = secrets.token_hex(4).upper()
            self.binding_deadline = self.clock() + 300
            self.candidate = None
            return self.binding_code

    def confirm_binding(self, candidate):
        with self.lock:
            if not self.binding_code or self.clock() >= self.binding_deadline or candidate != self.candidate:
                raise ValueError("群绑定已过期或发生变化，请重新绑定")
            config = dict(self.config, group=candidate["group"], corp=candidate["corp"],
                          group_name=candidate["name"], enabled=False)
            self.config_store.save(config)
            self.config = config
            self.binding_code, self.candidate = "", None
        self.emit("指定群绑定成功，等待本地启用确认")

    def enable(self, enabled, *, persist=True):
        if enabled:
            guard = getattr(self, "direct_admission", None)
            if guard is not None:
                guard("dingtalk", self.config)
        self.conversation.router.cancel_platform("dingtalk")
        with self.lock:
            self.routing_generation += 1
            config = dict(self.config, enabled=bool(enabled))
            if enabled:
                if persist:
                    self.config_store.save(config)
            self.config = config  # 停用先在内存生效，即使磁盘不可写也立即停止接收/执行。
            self.tokens.clear()
            self.reply_context.clear()
            self.binding_code, self.candidate = "", None
        if enabled:
            try:
                self.start()
            except Exception:
                self.config["enabled"] = False
                if persist:
                    self.config_store.save(self.config)
                raise
            self.emit("已启用，指定群全员可调用当前项目排障；新会话默认帮我批准")
        else:
            while True:
                try:
                    self.outbox.get_nowait()
                    self.outbox.task_done()
                except queue.Empty:
                    break
            if self.transport:
                self.transport.begin_close()
            for identifier in tuple(self.sessions):
                try:
                    self.conversation.stop(identifier)
                except ValueError:
                    pass
            self.emit("已停用，取消本项目钉钉排障并等待清理；原挂测继续")
            try:
                if persist:
                    self.config_store.save(config)
            except Exception:
                raise ValueError("本进程已停用，但停用设置保存失败；请修复文件权限，重启前重新保存") from None

    def receive(self, data):
        """Stream线程：仅校验身份/入箱，不等待模型或UI。"""
        message = RemoteMessage.parse(data)
        with self.lock:
            if self.stop_event.is_set() or message.robot != self.config["robot_code"]:
                return
            if (self.binding_code and self.clock() < self.binding_deadline
                    and message.text == "绑定 " + self.binding_code):
                self.candidate = dict(group=message.group, corp=message.corp,
                                      name=str(data.get("conversationTitle", "指定群"))[:160])
                return
            if (not self.config["enabled"] or message.group != self.config["group"]
                    or message.corp != self.config["corp"]):
                return
            if self.mailbox.admit(message):
                if valid_session_url(message.webhook):
                    self.reply_context[(message.corp, message.group, message.sender)] = (message.webhook, message.expires)
                self.emit("已接收群消息 " + message.id[:12] + "，等待会话处理")

    @staticmethod
    def identity(message):
        return message.corp, message.group, message.sender

    def _selected(self, message, value=None):
        key = "dingtalk_channel:" + hashlib.sha256(json.dumps(self.identity(message)).encode()).hexdigest()
        if value is not None:
            self.store.set_setting(key, value)
        return self.store.setting(key)

    def _session(self, message, channel, fresh=False):
        diagnostic = self.conversation.diagnostic
        with diagnostic.lock:
            target, profile = diagnostic.targets.get(channel), diagnostic.profile
        if target is None:
            raise ValueError("该通道不在当前项目已勾选的有效目标中，请在本地检查配置")
        if profile is None:
            raise ValueError("请先在本地AI工作台保存并选择模型")
        key = json.dumps((message.robot, *self.identity(message), channel), ensure_ascii=False)
        route = self.mailbox.routes().get(key)
        if route and not fresh:
            try:
                session = self.store.chat(route[0])
                if (session["target"] == asdict(target) and session["run_id"] == self.conversation.context.run_id
                        and profile_fingerprint(profile) == profile_fingerprint(self.conversation._profile(session))):
                    self.sessions.add(session["id"])
                    return session["id"]
            except ValueError:
                pass
        if route and route[0] in self.conversation.running:
            raise ValueError("原会话仍在排查或清理，请先停止并等待结束")
        source = dict(kind="dingtalk", group=message.group, corp=message.corp,
                      sender=message.sender, nickname=message.nickname, robot=message.robot)
        identifier = self.conversation.create_session(target, profile,
            title=f"钉钉·{message.nickname}·通道{channel}", source=source, default_permission=AUTO)
        self.mailbox.route(key, identifier, len(self.store.chat_items(identifier)))
        self.sessions.add(identifier)
        self.emit(f"群成员会话已关联：{identifier[:8]}，通道{channel}")
        return identifier

    def _existing(self, message, channel):
        source = dict(kind="dingtalk", robot=message.robot, corp=message.corp, group=message.group, sender=message.sender)
        active = self.conversation.router.current(source)
        if active:
            try:
                self.store.chat(active)
                return active
            except ValueError:
                pass
        key = json.dumps((message.robot, *self.identity(message), channel), ensure_ascii=False)
        route = self.mailbox.routes().get(key)
        if not route:
            raise ValueError("当前通道尚无钉钉会话，请先发送排障问题")
        self.store.chat(route[0])
        self.sessions.add(route[0])
        return route[0]

    def _dispatch(self, message):
        with self.lock:
            if (not self.config["enabled"] or message.group != self.config["group"]
                    or message.corp != self.config["corp"] or message.robot != self.config["robot_code"]):
                return
        kind, value = command(message.text)
        channel = self._selected(message)
        if kind == "帮助":
            self.reply(message, HELP, channel)
            return
        if kind in ("批准", "拒绝"):
            self._decide(message, value, kind == "批准")
            return
        if kind in ("问题", "通道", "新会话"):
            generation = self.routing_generation
            def allowed():
                with self.lock:
                    return (not self.stop_event.is_set() and generation == self.routing_generation
                        and self.config["enabled"] and message.group == self.config["group"]
                        and message.corp == self.config["corp"] and message.robot == self.config["robot_code"])
            return dispatch_remote(self, message, kind, value, "dingtalk", allowed)
        if kind in ("停止", "状态"):
            identifier = self._existing(message, channel)
            session = self.store.chat(identifier)
            channel = target_channel(session) if session.get("target") else target_label(session)
            if kind == "停止":
                self.conversation.stop(identifier)
                self._forget_tokens(identifier)
                self.reply(message, "已请求停止本轮排障，等待必要清理；原挂测继续", channel)
            else:
                session = self.store.chat(identifier)
                permission = self.conversation.permissions.status(identifier)
                self.reply(message, session["status"] + "；权限：" + permission["label"], channel)
            return

    def _forget_tokens(self, identifier):
        related = self.conversation.batch.related(identifier) if hasattr(self.conversation, "batch") else [identifier]
        with self.lock:
            self.tokens = {k: v for k, v in self.tokens.items() if v["session"] not in related}

    def _decide(self, message, token, approved):
        with self.lock:
            approval = self.tokens.get(token)
            if (not approval or approval["identity"] != self.identity(message)
                    or self.clock() >= approval["expires"]):
                raise ValueError("批准编号无效、已过期或不属于你发起的操作")
        action = self.store.action(approval["action"])
        if action_fingerprint(action) != approval["fingerprint"]:
            raise ValueError("操作内容已变化，旧批准无效")
        self.conversation.actions.decide(approval["session"], action["id"], approval["fingerprint"], approved,
            operator_source="dingtalk", operator_identity=json.dumps(self.identity(message)))
        with self.lock:
            self.tokens.pop(token, None)
        self.reply(message, "已批准本次具体操作" if approved else "已拒绝本次操作", target_channel(action) if action.get("target") else target_label(action))

    def _publish(self):
        for key, (identifier, cursor) in self.mailbox.routes().items():
            try:
                session = self.store.chat(identifier)
            except ValueError:
                continue
            source = session.get("source", {})
            if source.get("kind") != "dingtalk":
                continue
            message = RemoteMessage("", source["group"], source["corp"], source["sender"],
                                    source["nickname"], source["robot"], "")
            if (source["group"] != self.config["group"] or source["corp"] != self.config["corp"]
                    or source["robot"] != self.config["robot_code"]):
                continue
            messages = self.store.chat_items(identifier)
            for index in range(cursor, len(messages)):
                item = messages[index]
                text = str(item.get("text", ""))
                # 待批准详情由下面的不可变操作记录生成，替换桌面按钮指引。
                if item.get("role") == "assistant" and item.get("reply_id"):
                    if not self.reply_streams.offer(identifier, message, item, self._stream_title(message, session),
                                                   self.routing_generation):
                        break
                elif item.get("role") == "assistant" and "请点击“查看待确认操作”" in text:
                    pass
                elif item.get("role") != "user" and item.get("kind") not in ("context", "action"):
                    if not self.reply(message, text, target_channel(session) if session.get("target") else target_label(session)):
                        break
                self.mailbox.route(key, identifier, index + 1)
            self._publish_approval(identifier, message)
            draft = self.conversation.draft_message(identifier)
            if isinstance(draft, dict) and draft.get("text"):
                self.reply_streams.offer(identifier, message, draft, self._stream_title(message, session),
                                        self.routing_generation)

    def _publish_approval(self, identifier, message):
        with self.lock:
            self.tokens = {k: v for k, v in self.tokens.items()
                           if self.store.action(v["action"])["state"] == "waiting_approval"}
        actions = (self.conversation.batch.actions(identifier, ("waiting_approval",))
                   if session_scope(self.store.chat(identifier)) == "batch" else self.store.actions(identifier, ("waiting_approval",)))
        for action in actions:
            if action["id"] in self.local_only_approvals:
                continue
            with self.lock:
                if any(v["action"] == action["id"] for v in self.tokens.values()):
                    continue
            token = secrets.token_hex(4).upper()
            detail = (f"需要你批准：{action.get('assessment', {}).get('reason', '风险待确认')}\n"
                      f"操作：{action['name']}\n参数：{json.dumps(action['params'], ensure_ascii=False)}\n"
                      f"回复“批准 {token}”或“拒绝 {token}”；仅发起人有效，十分钟内单次使用。")
            if len(detail.encode("utf-8")) > 30000:
                if self.reply(message, "待批准操作内容过长，请在本地工作台核对完整内容后批准或拒绝。",
                              target_channel(action) if action.get("target") else target_label(action)):
                    self.local_only_approvals.add(action["id"])
                continue
            if self.reply(message, detail, target_channel(action) if action.get("target") else target_label(action)):
                with self.lock:
                    self.tokens[token] = dict(session=action["session_id"], action=action["id"],
                        fingerprint=action["fingerprint"], identity=self.identity(message), expires=self.clock() + 600)

    def _expire(self):
        with self.lock:
            expired = [(k, v) for k, v in self.tokens.items() if self.clock() >= v["expires"]]
        for token, value in expired:
            try:
                self.conversation.actions.decide(value["session"], value["action"], value["fingerprint"], False,
                                                  operator_source="dingtalk_expired")
                self.emit("批准编号已过期，本操作已拒绝")
            except ValueError:
                pass
            with self.lock:
                self.tokens.pop(token, None)

    def _sanitize(self, text, *, streaming=False):
        text = self.conversation.redactor.stream_text(text) if streaming else self.conversation.redactor.text(text)
        hidden = [self.config.get(k, "") for k in ("client_secret", "webhook", "secret")]
        with self.conversation.diagnostic.lock:
            hidden += [t.password for t in self.conversation.diagnostic.targets.values()]
        for profile in self.store.profiles():
            try:
                hidden.append(self.store.key(profile))
            except (ValueError, RuntimeError):
                pass
        # 已保存的设备/WiFi/远程访问凭据也不经新的群回复出口外发。
        for path in self.project_path.parent.glob("*.ini"):
            parser = configparser.RawConfigParser()
            with path.open(encoding="utf-8-sig") as stream:
                parser.read_file(stream)
            for section in parser.sections():
                for key, value in parser.items(section):
                    if (re.search(r"password|passwd|secret|token|psk|verification_code|^key$", key, re.I)
                            and not re.search(r"_(flag|enable|enabled|mode|length|timeout|retry)$", key, re.I)):
                        hidden.append(value.strip())
        if streaming:
            text = hold_secret_prefix(text, hidden)
        for secret in sorted(set(filter(None, hidden)), key=len, reverse=True):
            text = text.replace(secret, "<凭据已隐藏>")
        return re.sub(r"(?i)(access_token|session|ticket)=([^\s&]+)", r"\1=<凭据已隐藏>", text)

    def _stream_allowed(self, message, generation):
        with self.lock:
            return (not self.stop_event.is_set() and self.config["enabled"]
                    and generation == self.routing_generation and message.robot == self.config["robot_code"]
                    and message.corp == self.config["corp"] and message.group == self.config["group"])

    def _stream_card(self, message, generation):
        return DingTalkReplyCard(dict(self.config), lambda: self._stream_allowed(message, generation),
                                self.emit, self.card_token_cache)

    def _stream_title(self, message, session):
        return f"项目：{load_push_project_name(self.project_path)} | {target_label(session)} | {message.nickname}"

    def _send_stream_final(self, message, title, text, identifier, generation):
        for chunk in split_text(title + '\n' + text):
            if not self._stream_allowed(message, generation):
                raise CardStopped()
            self.emit("下发降级完整回复：POST 钉钉会话/群机器人接口（凭据省略）")
            session, expires = self.reply_context.get(self.identity(message), ("", 0))
            if session and expires > int(time.time() * 1000) + 10000:
                self.session_sender(session, chunk)
            else:
                self.sender(self.config["webhook"], self.config.get("secret", ""), chunk, at_all=False)
            if len(text) > 1000:
                self.stop_event.wait(self.send_interval)

    def reply(self, message, text, channel=None):
        if not text:
            return True
        try:
            project = load_push_project_name(self.project_path)
            header = f"项目：{project}" + ((f" | 通道{channel}" if isinstance(channel, int) else f" | {channel}") if channel is not None else "")
            header += " | " + message.nickname
            text = self._sanitize(header + "\n" + text)
            chunks = split_text(text)
            with self.lock:
                if self.outbox.maxsize - self.outbox.qsize() < len(chunks):
                    return False
                for index, chunk in enumerate(chunks):
                    self.outbox.put_nowait((message, f"[{index + 1}/{len(chunks)}] " + chunk))
            return True
        except Exception:
            self.emit("回复整理失败，正文留存在本地工作台；未发送未经检查的内容")
            return False

    def _loop(self):
        last_publish = 0
        while not self.stop_event.wait(.1):
            try:
                payload = self.mailbox.next()
                if payload:
                    message = RemoteMessage(**payload)
                    try:
                        self._dispatch(message)
                    except Exception as exc:
                        self.reply(message, str(exc), self._selected(message))
                        self.emit("消息处理未完成，详情已记录在对应会话或群反馈")
                    finally:
                        self.mailbox.finish(message.id)
                if (self.config["enabled"] and self.transport is not None
                        and not self.transport.idle and self.clock() - last_publish >= .5):
                    self._publish()
                    self._expire()
                    last_publish = self.clock()
                if (not self.config["enabled"] and self.binding_code and self.clock() >= self.binding_deadline):
                    self.binding_code, self.candidate = "", None
                    if self.transport:
                        self.transport.begin_close()
                # 独立订阅只用于唤醒/提示，轮询持久化记录可补齐队列溢出。
                while not self.updates.empty():
                    self.updates.get_nowait()
            except Exception:
                self.status("接入处理异常，本轮未自动重放操作，请检查本地工作台")

    def _send_loop(self):
        while not self.stop_event.is_set():
            self.reply_streams.tick()
            try:
                message, text = self.outbox.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                if (not self.config["enabled"] or message.group != self.config["group"]
                        or message.corp != self.config["corp"]):
                    continue
                session, expires = self.reply_context.get(self.identity(message), ("", 0))
                if session and expires > int(time.time() * 1000) + 10000:
                    self.session_sender(session, text)
                else:
                    self.sender(self.config["webhook"], self.config.get("secret", ""), text, at_all=False)
                self.emit("群回复发送成功（钉钉已接受）")
            except Exception:
                self.emit("群回复发送失败或结果未知，请在本地工作台核对；不会重新执行排障工具")
            finally:
                self.outbox.task_done()
            self.reply_streams.wait(self.stop_event, self.send_interval)

    def begin_close(self):
        self.conversation.router.cancel_platform("dingtalk")
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        if self.transport:
            self.transport.begin_close()
        for identifier in tuple(self.sessions):
            try:
                self.conversation.stop(identifier)
            except ValueError:
                pass
        self.tokens.clear()
        self.conversation.unsubscribe(self.updates)

    @property
    def idle(self):
        return (not self.worker.is_alive() and not self.sender_thread.is_alive()
                and (self.transport is None or self.transport.idle))

    def close(self):
        if not self.idle:
            raise ValueError("钉钉后台尚未结束")
        if self.lease:
            self.lease.close()
            self.lease = None
        self.mailbox.close()
