"""Route the local Qt case editor through the original case service."""
from src.models.qt_ai_cases import CaseRow, CaseView
from src.services.ai_case_store import FIELDS


class QtAiCases:
    def __init__(self, diagnostic):
        self.diagnostic = diagnostic

    def execute(self, operation, arguments):
        store = self.diagnostic.store
        selected, report_id, notice = None, '', ''
        existing_write = operation in ('ai_case_toggle', 'ai_case_delete') or (operation == 'ai_case_save' and arguments[0] is not None)
        if existing_write and (type(arguments[1]) is not int or arguments[1] < 1):
            raise ValueError('案例缺少有效版本，请刷新案例列表后重试')
        if operation == 'ai_case_open':
            selected, report_id = arguments
        elif operation == 'ai_case_from_report':
            report_id, = arguments
            store.report(report_id)
            self.diagnostic.emit(f'[AI案例] 从报告新建草稿：{report_id}')
        elif operation == 'ai_case_save':
            identifier, version, report_id, fields = arguments
            selected = self.diagnostic.confirm_case(report_id, *fields, case_id=identifier, expected_version=version)
            notice = f'已保存案例 #{selected}'
        else:
            identifier, version = arguments
            delete = operation == 'ai_case_delete'
            self.diagnostic.update_case_state(identifier, delete=delete, expected_version=version)
            if delete:
                notice = f'已删除案例 #{identifier}'
            else:
                selected = identifier
                notice = f'已更新案例 #{identifier} 的检索状态'
        rows = tuple(CaseRow(row['id'], row['version'], row['report_id'] or '', bool(row['active']),
                             tuple(row[key] for key in FIELDS[1:])) for row in store.cases(include_inactive=True))
        return CaseView(rows, selected, report_id, notice)
