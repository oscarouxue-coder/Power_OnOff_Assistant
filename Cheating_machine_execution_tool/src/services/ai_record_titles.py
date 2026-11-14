"""会话/报告的本地显示名称；不改正文、上下文或诊断任务。"""
import re


def clean_title(value):
    return " ".join(str(value or "").replace(chr(96), "").split())


def report_theme(payload):
    event = payload.get("event") or {}
    return clean_title(event.get("detail")) or clean_title(payload.get("question")) or "诊断报告"


class AiRecordTitles:
    def __init__(self, store, emit):
        self.store, self.emit = store, emit

    def chat_entries(self, rows):
        names = self.store.record_titles("chat")
        report_names = self.store.record_titles("report")
        entries = []
        for row in rows:
            identifier = row["id"]
            title = names.get(identifier) or clean_title(row.get("title"))
            if not names.get(identifier) and (not title or re.fullmatch(r"通道\d+排障", title)):
                title = ""
                source = row.get("source_report_id")
                if source:
                    try:
                        title = report_names.get(source) or report_theme(self.store.report(source))
                    except ValueError:
                        pass  # 来源报告可独立删除，仍允许查看会话。
                title = title or clean_title(self.store.first_chat_question(identifier)) or "新会话"
            profile = row.get("profile") or {}
            entries.append(dict(id=identifier, title=clean_title(title), created=row.get("created", ""),
                                channel=row.get("target", {}).get("channel", ""),
                                provider=profile.get("provider", ""), model=profile.get("model", ""),
                                status=row.get("status", ""), cycle=0))
        return entries

    def report_entries(self, rows):
        names = self.store.record_titles("report")
        return [dict(id=identifier, title=clean_title(names.get(identifier)) or report_theme(payload),
                     created=created, channel=payload.get("channel", ""),
                     provider=payload.get("provider", ""), model=payload.get("model", ""),
                     status=payload.get("status", ""), cycle=(payload.get("event") or {}).get("cycle", 0))
                for identifier, created, payload in rows]

    def rename(self, kind, identifier, value):
        try:
            title = clean_title(value)
            if not 1 <= len(title) <= 80:
                raise ValueError("名称须为1至80字")
            self.store.rename_record(kind, identifier, title)
        except Exception as exc:
            self.emit(f"[AI列表] {kind} {identifier} 重命名失败：{exc}")
            raise
        self.emit(f"[AI列表] {kind} {identifier} 重命名成功，已保存本地名称")
        return title
