"""Fail on unreviewed GUI actions; retain explicit pending business coverage.

After reviewing a GUI change, --update records the new action manifest and regenerates
the readable matrix. It never labels a pending business as implemented.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys


def gui_actions(root):
    paths = sorted((root / "src/ui").glob("*.py")) + [root / "line_check_assistant/app.py", root / "line_check_assistant/pipeline_window.py"]
    result = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        # Capture helper changes too; an unchanged button can route into a changed
        # business helper. A reviewed snapshot must not silently miss that change.
        file_code_sha256 = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
        functions = {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            keywords = {k.arg: k.value for k in node.keywords if k.arg}
            function = ast.unparse(node.func)
            if "command" not in keywords and not function.endswith((".bind", ".trace_add")):
                continue
            value = ast.dump(node, include_attributes=False)
            callbacks = sorted({n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute) and
                                isinstance(n.value, ast.Name) and n.value.id == "self" and n.attr in functions})
            result.append(dict(file=path.relative_to(root).as_posix(),
                file_code_sha256=file_code_sha256,
                action=hashlib.sha256(value.encode()).hexdigest(), expression=ast.unparse(node),
                callbacks={name: hashlib.sha256(functions[name].encode()).hexdigest() for name in callbacks}))
    return sorted(result, key=lambda item: (item["file"], item["action"]))


def render_matrix(catalog, actions):
    connected = sum(r["status"] == "connected" for r in catalog)
    pending = sum(r["status"] == "pending" for r in catalog)
    manual = sum(r["status"] == "manual_control" for r in catalog)
    partial = sum(r["status"] == "partial" for r in catalog)
    lines = ["# Capability Coverage Matrix", "", "本表由 scripts/verify_capability_coverage.py 生成；登记、自动化验证和现场验收分别判断。",
             "", f"业务清单 {len(catalog)} 项；已有接口 {connected} 项；部分接入 {partial} 项；待接入 {pending} 项；人工控制面 {manual} 项。",
             "现有诊断/交互接口不代表该组所有管理动作已开放；部分接入见限制列，不将分组数字称为最终覆盖率。",
             "", "| 功能ID | GUI业务 | 真实入口 | 业务实现 | AI接口 | 状态/限制 | 资源/风险 | 自动化测试入口 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in catalog:
        lines.append("| " + " | ".join((r["feature_id"], r["name"], r["gui_entry"], r["service"],
                      r["capability_id"] or "待接入", r["status"] + "：" + r["reason"], "/".join(r["resources"]) + "/" + r["risk"],
                      ', '.join(r['tests']) + '；Windows/真实模型及设备待验收' if r['tests'] else '待接入/人工控制，无执行验收')) + " |")
    lines += ["", "## GUI动作审查", "", f"当前审查快照包含 {len(actions)} 个按钮/菜单/绑定/变量回调。新增或改变入口会使门禁失败。",
              "界面辅助动作（窗口显隐/滚动/复制/显密/清屏等）不计业务覆盖；动态控件须结合运行测试复核。",
              "", "## 当前阶段", "", "固件升级与基础设施是首批；待接入条目保持，不能将首批通过表述为Full Capability Agent已经完成。",
              "暂停/恢复不是已存在的通用测试接口；SSH目前属于旧挂测路径。原始字节归档及A7有界缓冲不在本轮。", ""]
    return "\n".join(lines)


def check(root):
    manifest = root / "scripts/capability_gui_actions.json"
    errors = []
    if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")) != gui_actions(root):
        errors.append("GUI动作发生变化，须审查业务覆盖并更新capability_gui_actions.json")
    sys.path.insert(0, str(root))
    from src.services.capability_catalog import business_catalog
    catalog = business_catalog()
    ids = [r["feature_id"] for r in catalog]
    if len(set(ids)) != len(ids):
        errors.append("业务功能ID重复")
    functions = {}
    for row in catalog:
        filename = row.get('gui_file', 'line_check_assistant/app.py')
        if filename not in functions:
            path = root / filename
            tree = ast.parse(path.read_text(encoding='utf-8-sig')) if path.is_file() else ast.Module(body=[], type_ignores=[])
            functions[filename] = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        if row['gui_entry'] not in functions[filename]:
            errors.append('业务入口不存在：' + filename + ':' + row['gui_entry'])
    errors.extend('专项测试入口不存在：' + name for r in catalog for name in r['tests'] if not (root / 'tests' / name).is_file())
    expected = render_matrix(catalog, gui_actions(root))
    matrix = root.parent / "CAPABILITY_COVERAGE.md"
    if not matrix.is_file() or matrix.read_text(encoding="utf-8") != expected:
        errors.append("可读覆盖矩阵与机器清单不一致")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.update:
        sys.path.insert(0, str(root))
        from src.services.capability_catalog import business_catalog
        actions = gui_actions(root)
        (root / "scripts/capability_gui_actions.json").write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (root.parent / "CAPABILITY_COVERAGE.md").write_text(render_matrix(business_catalog(), actions), encoding="utf-8")
    errors = check(root)
    print("\n".join(errors) if errors else "CAPABILITY_COVERAGE_OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
