"""远程回复投影：最新快照合并、单卡节流、持久化去重；不重跑模型或业务。"""
import hashlib
import json
import threading
import time

from src.core.ai_reply_cards import CardRejected, CardStopped


def card_segment(text, limit=12000):
    """按真实JSON转义大小切段，保留正文字符；为平台封套预留空间。"""
    size = 0
    for index, char in enumerate(text):
        size += len(json.dumps(char, ensure_ascii=True)) - 2
        if size > limit:
            return text[:index]
    return text


class ReplyStreamService:
    def __init__(self, mailbox, card_factory, allowed, sanitize, send_final, emit, *, clock=time.monotonic):
        self.mailbox, self.card_factory, self.allowed = mailbox, card_factory, allowed
        self.sanitize, self.send_final, self.emit, self.clock = sanitize, send_final, emit, clock
        self.lock = threading.RLock()
        self.pending, self.last = {}, {}
        with mailbox.lock, mailbox.db:
            mailbox.db.execute("""CREATE TABLE IF NOT EXISTS reply_streams(
                id TEXT PRIMARY KEY, state TEXT NOT NULL, handle TEXT NOT NULL)""")
            # 上次可能已经投递；重启不再创建卡片或重复完整回复。
            interrupted = mailbox.db.execute("UPDATE reply_streams SET state='unknown' WHERE state IN ('sending','active')").rowcount
        if interrupted:
            self.emit("上次流式回复存在未确认投递，保留unknown；不会自动重发")

    def _row(self, identifier):
        with self.mailbox.lock:
            row = self.mailbox.db.execute("SELECT state,handle FROM reply_streams WHERE id=?", (identifier,)).fetchone()
        return (row[0], json.loads(row[1])) if row else ("new", {"offset": 0, "part": 0})

    def _save(self, identifier, state, handle):
        with self.mailbox.lock, self.mailbox.db:
            self.mailbox.db.execute("INSERT OR REPLACE INTO reply_streams VALUES(?,?,?)",
                                   (identifier, state, json.dumps(handle)))

    def offer(self, session, message, item, title, generation):
        """只有终态已被处理才允许调用方推进持久化游标。"""
        identifier = item.get("reply_id")
        if not identifier:
            return False
        with self.lock:
            state, _ = self._row(identifier)
            if state in ("done", "unknown", "skipped"):
                return True
            final = item.get("stream_state") != "generating"
            if state == "fallback" and not final:
                return False
            if identifier not in self.pending and len(self.pending) >= 128:
                return False
            previous = self.pending.get(identifier)
            if previous and previous[2].get("stream_state") != "generating":
                return False  # 晚到草稿不能覆盖已收束的正文。
            self.pending[identifier] = (session, message, dict(item), title, generation)
            return False

    def tick(self):
        """仅在平台发送线程调用；网络操作不持有生产者锁。"""
        with self.lock:
            items = tuple(self.pending.items())
        for identifier, snapshot in items:
            session, message, item, title, generation = snapshot
            final = item.get("stream_state") != "generating"
            now = self.clock()
            if not final and now - self.last.get(identifier, -2) < 1:
                continue
            if not self.allowed(message, generation):
                self._save(identifier, "skipped", {})
                self._remove(identifier, snapshot)
                self.emit("流式回复跳过：聊天已停用或身份/代次已变化")
                continue
            state, handle = self._row(identifier)
            if state in ("done", "unknown", "skipped"):
                self._remove(identifier, snapshot)
                continue
            try:
                failed = item.get("stream_state") in ("failed", "cancelled")
                suffix = ("\n\n[回复未完成，已取消]" if item.get("stream_state") == "cancelled"
                          else "\n\n[回复未完成，生成失败]")
                if failed and item["text"].endswith(suffix):
                    # 终止标记不能使此前暂扣的凭据前缀在失败收尾时重新外发。
                    text = self.sanitize(item["text"][:-len(suffix)], streaming=True) + suffix
                else:
                    text = self.sanitize(item["text"], streaming=not final or failed)
                heading = self.sanitize(title)
                if not text and not final:
                    continue
                if state == "fallback":
                    if final:
                        self._save(identifier, "sending", handle)
                        self.send_final(message, heading, text, identifier, generation)
                        self._save(identifier, "done", {})
                        self._remove(identifier, snapshot)
                        self.emit("流式回复已降级发送完整结果")
                    continue
                card = self.card_factory(message, generation)
                offset = handle.get("offset", 0)
                remaining = text[offset:]
                if not remaining and not handle.get("card"):
                    if final:
                        self._save(identifier, "done", {})
                        self._remove(identifier, snapshot)
                    continue
                segment = card_segment(remaining)
                full_segment = len(segment) < len(remaining)
                expired = bool(handle.get("card")) and now - handle.get("opened", now) >= 540
                closing = final or full_segment or expired
                digest = hashlib.sha256(segment.encode()).hexdigest()
                if not closing and handle.get("digest") == digest:
                    continue
                # 先持久化请求意图；崩溃/超时后不重放投递。
                self._save(identifier, "sending", handle)
                if not handle.get("card"):
                    part_id = hashlib.sha256((identifier + ":" + str(handle.get("part", 0))).encode()).hexdigest()[:32]
                    handle["card"] = card.create(message, heading, segment, part_id)
                    handle["opened"] = now
                card.update(handle["card"], segment, closing,
                            failed=failed)
                self.last[identifier] = now
                handle["digest"] = digest
                if closing:
                    handle.update(offset=offset + len(segment), part=handle.get("part", 0) + 1)
                    handle.pop("card", None)
                    handle.pop("digest", None)
                if final and not full_segment:
                    self._save(identifier, "done", {})
                    self._remove(identifier, snapshot)
                    self.emit("流式回复收尾成功" if item.get("stream_state") == "completed" else "未完成回复已收尾")
                else:
                    self._save(identifier, "active", handle)
            except CardStopped:
                self._save(identifier, "skipped", {})
                self._remove(identifier, snapshot)
            except CardRejected as exc:
                if state != "fallback" and handle.get("card", {}).get("final_text_accepted") and final and not full_segment:
                    self._save(identifier, "done", {})
                    self._remove(identifier, snapshot)
                    self.emit("流式正文已投递，卡片状态收尾被拒绝；请核对平台权限，不重复发送正文")
                    continue
                if state == "fallback":
                    self._save(identifier, "unknown", handle)
                    self.emit("降级完整回复未被接受，请在本地核对；不会自动重发")
                    self._remove(identifier, snapshot)
                else:
                    if handle.get("card"):
                        try:
                            card.close(handle["card"], segment, True)
                        except Exception:
                            self.emit("旧流式卡片未确认关闭，完整结果将单独发送；请在本地核对")
                    self._save(identifier, "fallback", handle)
                    self.emit("流式卡片不可用，降级完整回复：" + str(exc))
                    if not final:
                        self._remove(identifier, snapshot)
            except Exception:
                self._save(identifier, "unknown", handle)
                self._remove(identifier, snapshot)
                self.emit("流式回复投递/更新结果未知，请在本地核对；不会重发或重新执行业务")

    def _remove(self, identifier, snapshot):
        with self.lock:
            if self.pending.get(identifier) is snapshot:
                self.pending.pop(identifier, None)
        self.last.pop(identifier, None)

    def wait(self, stop, duration):
        deadline = time.monotonic() + duration
        while not stop.wait(min(.1, max(0, deadline - time.monotonic()))):
            self.tick()
            if time.monotonic() >= deadline:
                break
