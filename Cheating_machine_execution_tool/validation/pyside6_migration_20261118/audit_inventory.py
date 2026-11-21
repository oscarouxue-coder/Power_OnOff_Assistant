"""Read-only AST inventory for migration Phase 0; never imports application code."""
import ast
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
VARIABLES = {'StringVar', 'BooleanVar', 'IntVar', 'DoubleVar', 'Variable'}
WINDOWS = {'Tk', 'Toplevel', 'QMainWindow', 'QDialog'}
WIDGETS = WINDOWS | {'Frame', 'Canvas', 'Notebook', 'PanedWindow', 'Menu'}


def main():
    records = []
    for path in sorted([*ROOT.joinpath('src').rglob('*.py'),
                        *ROOT.joinpath('line_check_assistant').rglob('*.py'),
                        ROOT / 'run_line_check_assistant.py']):
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source, filename=str(path))
        imports, classes, windows, variables, timers, bindings, widgets = [], [], [], [], [], [], Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append('.' * node.level + (node.module or ''))
            elif isinstance(node, ast.ClassDef):
                classes.append(dict(name=node.name, line=node.lineno,
                                    bases=[ast.get_source_segment(source, base) for base in node.bases]))
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else '')
                if name in WINDOWS:
                    windows.append(dict(kind=name, line=node.lineno))
                if name in VARIABLES:
                    variables.append(dict(kind=name, line=node.lineno))
                if name in WIDGETS:
                    widgets[name] += 1
                if name in ('after', 'after_idle', 'after_cancel'):
                    timers.append(dict(kind=name, line=node.lineno))
                if name in ('bind', 'bind_all', 'protocol', 'trace_add'):
                    bindings.append(dict(kind=name, line=node.lineno))
        gui_imports = [name for name in imports if name.split('.')[0] in ('tkinter', 'PyQt5', 'PySide6')
                       or name.startswith('src.ui') or name in ('.ui', '.pipeline_window')]
        records.append(dict(path=path.relative_to(ROOT).as_posix(), lines=len(source.splitlines()),
                            imports=sorted(set(imports)), gui_dependencies=gui_imports,
                            classes=classes, window_calls=windows, variable_calls=variables,
                            timer_calls=timers, bindings=bindings, widget_calls=dict(widgets)))
    summary = dict(source_files=len(records), source_lines=sum(r['lines'] for r in records),
                   files_with_gui_dependencies=sum(bool(r['gui_dependencies']) for r in records),
                   window_constructor_sites=sum(len(r['window_calls']) for r in records),
                   variable_constructor_sites=sum(len(r['variable_calls']) for r in records),
                   timer_sites=sum(len(r['timer_calls']) for r in records),
                   event_binding_sites=sum(len(r['bindings']) for r in records),
                   scope='src + line_check_assistant + launcher; static sites, not runtime counts')
    (OUT / 'source_inventory.json').write_text(json.dumps(dict(summary=summary, files=records),
                                                          ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# GUI 文件与类清单', '',
             '由 `audit_inventory.py` 静态生成；构造点不等于独立窗口数量。间接导入、动态工厂与运行时行为仍需逐模块验证。', '',
             '| 文件 | 类及定义行 | 窗口构造位置 | Var / 定时器 / 绑定 |',
             '| --- | --- | --- | --- |']
    for r in records:
        if not (r['gui_dependencies'] or r['window_calls'] or r['variable_calls']):
            continue
        classes = ', '.join(f"{c['name']}:{c['line']}" for c in r['classes']) or '—'
        windows = ', '.join(f"{c['kind']}:{c['line']}" for c in r['window_calls']) or '—'
        lines.append(f"| `{r['path']}` | {classes} | {windows} | {len(r['variable_calls'])} / {len(r['timer_calls'])} / {len(r['bindings'])} |")
    (OUT / 'GUI_INVENTORY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
