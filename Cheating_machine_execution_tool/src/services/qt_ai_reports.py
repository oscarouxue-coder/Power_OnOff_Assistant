"""Read and manage reports through the current project's diagnostic service."""
from src.models.capabilities import fingerprint
from src.models.qt_ai_reports import ReportDetail, ReportRow, ReportView
from src.utils.ai_output import format_diagnostic_evidence


class QtAiReports:
    def __init__(self, diagnostic, titles):
        self.diagnostic = diagnostic
        self.store = diagnostic.store
        self.titles = titles

    def _detail(self, identifier):
        payload = self.store.report(identifier)
        return ReportDetail(identifier, str(payload.get('report', '')),
                            format_diagnostic_evidence(payload.get('evidence', '')), fingerprint(payload))

    def execute(self, operation, args):
        if operation == 'ai_report_select':
            return self._detail(args[0])
        selected = args[0]
        deleted = None
        if operation == 'ai_report_rename':
            self.titles.rename('report', selected, self.diagnostic.redactor.text(args[1]))
        elif operation == 'ai_report_delete':
            deleted = self.diagnostic.delete_reports(args[1])
        entries = self.titles.report_entries(self.store.reports(limit=None))
        busy = self.diagnostic.report_deletion_busy_ids()
        rows = tuple(ReportRow(entry['id'], entry['title'], entry['created'], str(entry['channel']),
                               entry['provider'], entry['model'], entry['status'], entry['id'] in busy)
                     for entry in entries)
        if selected not in {row.identifier for row in rows}:
            selected = rows[0].identifier if rows else ''
        return ReportView(rows, self._detail(selected) if selected else None, deleted)
