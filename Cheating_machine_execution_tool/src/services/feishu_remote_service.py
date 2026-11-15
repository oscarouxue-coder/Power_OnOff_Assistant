"""飞书群聊/单聊接入；复用AI业务服务，平台路由和启停独立。"""
from dataclasses import asdict, replace
from src.services.ai_session_router import dispatch_remote
from src.models.ai_session_scope import target_channel, target_label, session_scope
import hashlib
import json
from pathlib import Path
import queue
import secrets
import threading
import time

from src.core.feishu_client import FeishuApi
from src.core.feishu_stream import FeishuStream, FeishuInstanceLease
from src.models.ai_actions import action_fingerprint
from src.models.ai_permissions import PERMISSION_LABELS
from src.models.feishu_remote import FeishuMessage, HELP, command
from src.services.ai_store import profile_fingerprint
from src.services.feishu_output import reply_posts, sanitize
from src.services.feishu_remote_store import FeishuMailbox
from src.services.message_push_config_service import load_push_project_name


class FeishuRemoteService:
    def __init__(self, conversation, config_store, project_path, *, transport_factory=FeishuStream,
                 lease_factory=FeishuInstanceLease, api_factory=FeishuApi, clock=time.monotonic,
                 autostart=True, send_interval=.35, project_guarded=False):
        self.conversation, self.store = conversation, conversation.store
        self.config_store, self.project_path = config_store, Path(project_path)
        self.config = config_store.load()
        self.mailbox = FeishuMailbox(config_store.directory)
        self.transport_factory, self.lease_factory, self.api_factory = transport_factory, lease_factory, api_factory
        self.clock, self.send_interval, self.project_guarded = clock, send_interval, project_guarded
        self.api = api_factory(self.config["app_id"], self.config["app_secret"])
        self.lock = threading.RLock()
        self.transport, self.lease = None, None
        self.connection_status = "未启用"
        self.binding_code, self.binding_deadline, self.candidate = "", 0, None
        self.tokens, self.local_only_approvals = {}, set()
        self.sessions = {s["id"] for s in self.store.chats() if (s.get("source") or {}).get("kind") == "feishu"}
        self.generations = dict(group=0, p2p=0)
        self.stop_event = threading.Event()
        self.outbox = queue.Queue(maxsize=128)
        self.updates = conversation.subscribe()
        self.worker = threading.Thread(target=self._loop, name="feishu-ai", daemon=True)
        self.sender_thread = threading.Thread(target=self._send_loop, name="feishu-reply", daemon=True)
        if autostart:
            self.worker.start()
            self.sender_thread.start()

    def emit(self, text):
        self.conversation.emit("[飞书接入] " + text)

    def status(self, text):
        with self.lock:
            changed = self.connection_status != text
            self.connection_status = text
        if changed:
            self.emit(text)

    def snapshot(self):
        with self.lock:
            return dict(status=self.connection_status, enabled=self.config["enabled"],
                        group_enabled=self.config["group_enabled"], p2p_enabled=self.config["p2p_enabled"],
                        candidate=dict(self.candidate) if self.candidate else None,
                        binding=bool(self.binding_code and self.clock() < self.binding_deadline))

    def start(self):
        if self.stop_event.is_set():
            raise ValueError("飞书接入正在退出")
        if self.transport is not None:
            if not self.transport.idle:
                if self.transport.stop.is_set():
                    raise ValueError("请等待原飞书连接停止后再启用")
                return
            self.transport = None
        if self.lease:
            self.lease.close()
            self.lease = None
        if not self.config["app_id"] or not self.config["app_secret"]:
            raise ValueError("请先保存飞书App ID和App Secret")
        identities = ["feishu:app:" + self.config["app_id"]]
        if not self.project_guarded:
            identities.append("project:" + str(self.config_store.directory.resolve()))
        self.lease = self.lease_factory(*identities)
        self.lease.acquire()
        try:
            self.transport = self.transport_factory(self.config["app_id"], self.config["app_secret"],
                                                    self.receive, self.status, api=self.api)
            self.transport.start()
        except Exception:
            self.lease.close()
            self.lease, self.transport = None, None
            raise

    def update_config(self, config):
        with self.lock:
            if self.config["enabled"] or any(s in self.conversation.running for s in self.sessions):
                raise ValueError("请先停用飞书排障并等待清理")
            if self.transport and not self.transport.idle:
                raise ValueError("请等待飞书连接结束")
            self.config = dict(config)
            self.api = self.api_factory(config["app_id"], config["app_secret"])
            self.tokens.clear()
            for kind in self.generations:
                self.generations[kind] += 1

    def begin_binding(self):
        if self.config["group_enabled"] or self.config["push_enabled"]:
            raise ValueError("请先关闭飞书群排障及测试通知，再重新绑定")
        self.start()
        with self.lock:
            self.binding_code, self.binding_deadline = secrets.token_hex(4).upper(), self.clock() + 300
            self.candidate = None
        self.emit("开始群绑定，五分钟内等待群内@本机器人发送绑定码")
        return self.binding_code

    def confirm_binding(self, candidate):
        with self.lock:
            if not self.binding_code or self.clock() >= self.binding_deadline or candidate != self.candidate:
                raise ValueError("群绑定已过期或发生变化，请重新绑定")
            config = dict(self.config, group=candidate["group"], corp=candidate["corp"], group_name=candidate["name"],
                          push_revision=self.config["push_revision"] + 1)
            self.config_store.save(config)
            self.config = config
            self.binding_code, self.candidate = "", None
            self.generations["group"] += 1
            if not self.config["enabled"] and self.transport:
                self.transport.begin_close()
        self.emit("指定群绑定成功，等待本机启用确认")

    def cancel_binding(self):
        with self.lock:
            self.binding_code, self.candidate = "", None
            if not self.config["enabled"] and self.transport:
                self.transport.begin_close()
        self.emit("已取消群绑定")

    def enable(self, kind, enabled):
        if kind not in ("group", "p2p"):
            raise ValueError("飞书会话类型无效")
        self.conversation.router.cancel_platform("feishu", kind)
        with self.lock:
            if enabled and any(s in self.conversation.running
                               and self.store.chat(s).get("source", {}).get("chat_type") == kind for s in self.sessions):
                raise ValueError("请先等待该类型原会话停止并清理结束")
            config = dict(self.config, **{kind + "_enabled": bool(enabled)})
            config["enabled"] = config["group_enabled"] or config["p2p_enabled"]
            config = self.config_store.validate(config)
            if enabled:
                # 停用期间产生的本地记录不在重新启用时自动外发。
                for key, (identifier, _) in self.mailbox.routes().items():
                    try:
                        if self.store.chat(identifier).get("source", {}).get("chat_type") == kind:
                            self.mailbox.route(key, identifier, len(self.store.chat_items(identifier)))
                    except ValueError:
                        pass
                self.config_store.save(config)
            self.config = config  # 停用先在内存生效，磁盘失败也不能继续调用。
            self.generations[kind] += 1
            self.tokens = {k: v for k, v in self.tokens.items() if v["identity"][2] != kind}
        if enabled:
            try:
                self.start()
            except Exception:
                with self.lock:
                    self.config[kind + "_enabled"] = False
                    self.config["enabled"] = self.config["group_enabled"] or self.config["p2p_enabled"]
                    self.config_store.save(self.config)
                raise
            self.emit(("群聊" if kind == "group" else "单聊") + "AI排障已启用，新会话默认完全访问；保留手动权限选择")
        else:
            for identifier in tuple(self.sessions):
                try:
                    if self.store.chat(identifier).get("source", {}).get("chat_type") == kind:
                        self.conversation.stop(identifier)
                except ValueError:
                    pass
            if not self.config["enabled"] and not self.binding_code and self.transport:
                self.transport.begin_close()
            self.emit(("群聊" if kind == "group" else "单聊") + "AI排障已停用，等待对应会话清理；原挂测继续")
            try:
                self.config_store.save(self.config)
            except Exception:
                raise ValueError("本进程已停用，但飞书停用设置保存失败；请修复权限并在重启前重新保存") from None

    def set_push_enabled(self, enabled):
        with self.lock:
            config = dict(self.config, push_enabled=bool(enabled), push_revision=self.config["push_revision"] + 1)
            if not enabled:
                self.config = config
            try:
                self.config_store.save(config)
            except Exception:
                if not enabled:
                    raise ValueError("本进程飞书测试通知已停用，但设置保存失败；请修复权限并在重启前重新保存") from None
                raise
            self.config = config
        self.emit("飞书测试通知已" + ("启用" if enabled else "关闭") + "，仅发送测试结果")

    def _allowed(self, message):
        if self.stop_event.is_set() or message.robot != self.config["app_id"]:
            return False
        if self.config["corp"] and message.corp != self.config["corp"]:
            return False
        return ((message.chat_type == "group" and self.config["group_enabled"]
                 and message.group == self.config["group"] and message.corp == self.config["corp"])
                or (message.chat_type == "p2p" and self.config["p2p_enabled"]))

    def receive(self, data, bot_id):
        message = FeishuMessage.parse(data, self.config["app_id"], bot_id)
        with self.lock:
            if self.stop_event.is_set():
                return
            if self.config["corp"] and message.corp != self.config["corp"]:
                return
            if (message.chat_type == "group" and self.binding_code and self.clock() < self.binding_deadline
                    and message.text == "绑定 " + self.binding_code):
                self.candidate = dict(group=message.group, corp=message.corp, name="飞书群 " + message.group)
                self.emit("已收到群绑定申请，等待本机核对群ID")
                return
            if not self._allowed(message):
                self.emit("跳过未授权聊天或未启用类型的消息")
                return
            if not self.config["corp"]:
                # 企业自建应用的可信长连接事件钉住企业，拒绝跨企业发送者。
                config = dict(self.config, corp=message.corp)
                self.config_store.save(config)
                self.config = config
            message = replace(message, generation=self.generations[message.chat_type])
            if self.mailbox.admit(message):
                self.emit("已接收" + ("群聊" if message.chat_type == "group" else "单聊") + "消息 " + message.id[:12])

    @staticmethod
    def identity(message):
        return message.robot, message.corp, message.chat_type, message.group, message.sender

    def _selected(self, message, value=None):
        key = "feishu_channel:" + hashlib.sha256(json.dumps(self.identity(message)).encode()).hexdigest()
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
        source = dict(kind="feishu", group=message.group, corp=message.corp,
                      sender=message.sender, nickname=message.nickname, robot=message.robot, chat_type=message.chat_type)
        identifier = self.conversation.create_session(target, profile,
            title=f"飞书·{message.nickname}·通道{channel}", source=source)
        self.mailbox.route(key, identifier, len(self.store.chat_items(identifier)))
        self.sessions.add(identifier)
        self.emit(f"飞书成员会话已关联：{identifier[:8]}，通道{channel}")
        return identifier

    def _existing(self, message, channel):
        source = dict(kind="feishu", robot=message.robot, corp=message.corp, group=message.group,
                      sender=message.sender, chat_type=message.chat_type)
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
            raise ValueError("当前通道尚无飞书会话，请先发送排障问题")
        self.store.chat(route[0])
        self.sessions.add(route[0])
        return route[0]

    def _dispatch(self, message):
        with self.lock:
            if not self._allowed(message) or message.generation != self.generations[message.chat_type]:
                return
        return self._dispatch_locked(message)

    def _dispatch_locked(self, message):
        kind, value = command(message.text)
        channel = self._selected(message)
        if kind == "帮助":
            self.reply(message, HELP, channel)
            return
        if kind in ("批准", "拒绝"):
            self._decide(message, value, kind == "批准")
            return
        if kind in ("问题", "通道", "新会话"):
            def allowed():
                with self.lock:
                    return self._allowed(message) and message.generation == self.generations[message.chat_type]
            return dispatch_remote(self, message, kind, value, "feishu", allowed)
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
                self.reply(message, "**状态**：" + session["status"] + "\n\n**权限**：" + permission["label"], channel)
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
            operator_source="feishu", operator_identity=json.dumps(self.identity(message)))
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
            if source.get("kind") != "feishu":
                continue
            message = FeishuMessage("", source["group"], source["corp"], source["sender"],
                                    source["nickname"], source["robot"], "", source["chat_type"])
            if not self._allowed(message):
                continue
            messages = self.store.chat_items(identifier)
            for index in range(cursor, len(messages)):
                item = messages[index]
                text = str(item.get("text", ""))
                # 待批准详情由下面的不可变操作记录生成，替换桌面按钮指引。
                if item.get("role") == "assistant" and "请点击“查看待确认操作”" in text:
                    pass
                elif (item.get("role") == "system" and item.get("kind") == "recovery"
                      and text.strip() == "本轮恢复状态：无临时修改"):
                    self.emit("飞书回复跳过：本轮无临时修改；完整恢复记录保留本地")
                elif item.get("role") != "user" and item.get("kind") not in ("context", "action"):
                    if not self.reply(message, text, target_channel(session) if session.get("target") else target_label(session)):
                        break
                self.mailbox.route(key, identifier, index + 1)
            self._publish_approval(identifier, message)

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
            detail = (f"**需要你批准**\n\n"
                      f"**原因**：{action.get('assessment', {}).get('reason', '风险待确认')}\n\n"
                      f"**操作**：`{action['name']}`\n\n"
                      f"**参数**\n```json\n{json.dumps(action['params'], ensure_ascii=False, indent=2)}\n```\n\n"
                      f"回复 **批准 {token}** 或 **拒绝 {token}**\n\n"
                      "仅发起人有效，十分钟内单次使用。")
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
                                                  operator_source="feishu_expired")
                self.emit("批准编号已过期，本操作已拒绝")
            except ValueError:
                pass
            with self.lock:
                self.tokens.pop(token, None)

    def _sanitize(self, text):
        return sanitize(text, self.project_path, (self.config["app_secret"],), self.conversation)

    def reply(self, message, text, channel=None, *, markdown=True):
        if not text:
            return True
        try:
            project = load_push_project_name(self.project_path)
            header = f"项目：{project}" + ((f" | 通道{channel}" if isinstance(channel, int) else f" | {channel}") if channel is not None else "")
            title = self._sanitize(header + " | " + message.nickname)
            chunks = reply_posts(message.group, title, self._sanitize(text), markdown=markdown)
            with self.lock:
                if not self._allowed(message) or self.outbox.maxsize - self.outbox.qsize() < len(chunks):
                    return False
                generation = self.generations[message.chat_type]
                for chunk in chunks:
                    self.outbox.put_nowait((message, chunk, generation))
            return True
        except Exception:
            self.emit("回复整理失败，正文保留本地；跳过未经检查的外发内容")
            return False

    def _loop(self):
        last_publish = 0
        while not self.stop_event.wait(.1):
            try:
                payload = self.mailbox.next()
                if payload:
                    message = FeishuMessage(**payload)
                    try:
                        self._dispatch(message)
                    except Exception as exc:
                        self.reply(message, str(exc), self._selected(message))
                        self.emit("消息处理未完成，请核对对应会话")
                    finally:
                        self.mailbox.finish(message.id)
                if (self.config["enabled"] and self.transport is not None and not self.transport.idle
                        and self.clock() - last_publish >= .5):
                    self._publish()
                    self._expire()
                    last_publish = self.clock()
                if self.binding_code and self.clock() >= self.binding_deadline:
                    self.cancel_binding()
                    self.emit("群绑定码已过期")
                while not self.updates.empty():
                    self.updates.get_nowait()
            except Exception:
                self.status("飞书处理异常，本轮未自动重放操作，请检查本地工作台")

    def _send_loop(self):
        while not self.stop_event.is_set():
            try:
                message, post, generation = self.outbox.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    allowed = self._allowed(message) and generation == self.generations[message.chat_type]
                if not allowed:
                    continue
                self.emit("下发飞书回复：POST /open-apis/im/v1/messages（凭据省略）")
                self.api.send_post(message.group, post)
                self.emit("飞书回复发送成功（接口已接受）")
            except Exception:
                self.emit("飞书回复发送失败或结果未知，请在本地核对；不会重新执行排障工具")
            finally:
                self.outbox.task_done()
            self.stop_event.wait(self.send_interval)

    def begin_close(self):
        self.conversation.router.cancel_platform("feishu")
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
        self.mailbox.discard_pending()
        self.conversation.unsubscribe(self.updates)

    @property
    def idle(self):
        return (not self.worker.is_alive() and not self.sender_thread.is_alive()
                and (self.transport is None or self.transport.idle))

    def close(self):
        if not self.idle:
            raise ValueError("飞书后台尚未结束")
        if self.lease:
            self.lease.close()
            self.lease = None
        self.mailbox.close()
