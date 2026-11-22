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
    paths = sorted((root / "src/ui").rglob("*.py")) + [root / "line_check_assistant/app.py", root / "line_check_assistant/pipeline_window.py"]
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
            qt_menu_callback = function.endswith('.addAction') and len(node.args) > 1
            if "command" not in keywords and not function.endswith((".bind", ".trace_add", ".connect")) and not qt_menu_callback:
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
              "暂停/恢复不是已存在的通用测试接口；SSH目前属于旧挂测路径。原始字节归档及A7有界缓冲不在本轮。",
              "", "## Qt迁移入口审查", "",
              "Qt信号connect、菜单addAction及子目录界面纳入动作快照。Qt项目新建/打开/旧配置导入/保存/重命名/复制/关闭复用WorkspaceService与ProjectStore，沿用projects.*的manual_control边界。旧导入执行原备份、配置和历史转换，启用平台与远程项目范围仍须在原入口重新确认。",
              "Qt自动开关机、环境检查与三项全流程复用aging.start、network.line_check及pipeline.start，通过原CapabilityService、Jobs和资源准入。全流程本机明确选择三项，复用Qt串口终端逐个预启动已确认通道，日志目录和工序绑定项目。停止只取消当前Qt准入的原任务，不接管旧GUI批次。",
              "Qt单次自动上/下电通过仅本机界面可用的power.qt_single和一次确认令牌绑定项目、通道、所选电源口及方向，沿用原Jobs资源准入和单次电源服务。空电源口仅记录人工重启确认。通用power.on/off仍使用项目配置电源口。",
              "Qt最近项目沿用 projects.open 与 projects.forget 的本机人工控制面。菜单使用原工作区最近记录，移除仅改记录文件，项目仍保持打开。新建、打开、保存快捷键复用原菜单动作。打开项目目录仅由本机操作员触发，按所选已打开项目定位目录。",
              "Qt选择导入的接入配置沿用 projects.imported_connection 本机人工控制面。只展示来源标签，保存前复核候选、当前配置和停用状态，沿用原加密存储和连接占用保护。",
              "Qt核实未知任务复用 projects.resolve_unknown 本机人工控制面。操作员提供依据并再次确认后，由原WorkspaceService留存依据、解除所选旧GUI保护并标记原运行记录。保留原结果，不接入正式Job结果更改，也不新增AI或远程入口。",
              "Qt任务历史的现场核实使用原CapabilityJobs.resolve_unknown本机人工审阅流程。一项确认绑定选定项目、完整Job标识和原记录版本。复用原可信身份、结果存储及资源保护，不新增模型或远程权限。",
              "Qt任务历史可以分页查看旧工作台运行记录。只读取已打开项目的原 GUI 运行记录，历史页没有设备控制操作，业务任务和事件继续使用原项目 Job 库。",
              "Qt AI 模型连接复用 ai.profiles、ai.source_ip、ai.models_test 对应的原共享模型存储、项目选择、出口枚举与模型客户端。本机配置编辑及加密密钥写入只出现在人工控制面。连接测试仅调用原无项目资料样例，Qt 未扩大模型、DUT 或远程权限。",
              "Qt Ai助手复用原 AiConversationService、项目会话持久化和证据服务。普通问答无工具，报告会话可分析留存材料。本机电脑连续诊断复用原只读工具、PcConversationExecutor 与原停止机制，沿用模型工具资格及项目会话约束。创建和切换会话是本机人工操作。Qt 本机通道诊断由 diagnostics.qt.configure 核对操作员、目标与策略，监控和多通道排查复用 AiMonitorService 和 AiBatchService。",
              "Qt 实时 AI 日志复用既有主界面摘要规则，在显示交接缓冲前压缩已知正常过程并保留可辨识异常。工作区归档仍保存原服务已过滤模型密钥的原文。显示处理不授予采集、执行或远程权限。",
              "Qt AI 会话与 Tk 共用原 Markdown 展示解析，链接和未支持标记保持为文字。会话状态与正文独立刷新。Enter / Ctrl+Enter 复用现有发送入口，Alt+Enter 插入换行；模型与设备权限沿用原入口。",
              "Qt 排查进展沿用当前项目及所选会话的留存记录，使用与 Tk 共用的只读展示逻辑。查看进展属于本地人工查阅，不启动诊断和采集。",
              "Qt 会话权限查询由本机操作员发起，通过原会话权限服务核对偏好、有效模式和取证资格，归入人工控制面。",
              "Qt 网关登记实例、本机网关启停及撤销沿用原管理服务。具体操作审批复核所选项目会话、操作编号与指纹后调用原决定服务。两项均为本机人工控制面。",
              "一次性配对码的签发、复制和兑换仅供本机人工操作。通过原网关与实例管理服务复核已保存的成员范围及实例槽位；不登记为 AI 或远程可执行能力。",
              "Qt 管理会话属于本机人工控制面。重命名使用原标题服务，批量删除提交操作者确认时固定的项目会话 ID。沿用原 AiConversationService 的忙碌拦截、子会话管理和删除事务；模型和远程工具不提供此界面控制入口。",
              "Qt 诊断报告复用 ai.reports 对应的项目报告库、标题服务、删除保护和原报告接手服务。批量删除复核确认名单。旧报告由本机确认同通道目标并复核当前快照，接手只创建留存会话，主动诊断通过本机确认的当前通道会话进入。",
              "Qt 已确认案例沿用 ai.cases 的共享库、版本检查和启停/删除服务。从报告仅关联来源，新增和修订需操作者填写五项事实并本机确认，属于 ai.case_confirmation 人工控制面。",
              "Qt 全局设置检查更新使用 updates.check / updates.download 对应的原 AppUpdateService。交互下载由本机选择 ZIP 位置及确认覆盖，沿用原 HTTPS、校验和临时文件保护。下载完成可打开目录，安装仍为人工操作。",
              "Qt 设备管理复用 resources.refresh 对应的只读主机枚举、现有项目通道快照与工作区活动租约。",
              "Qt 网卡改名从通道选择触发，channels.editor.rename_* 只供本机 GUI。确认绑定网卡 GUID、项目通道草稿及新名称，复用原单次 Windows 改名和回读，复核后同步所有打开项目。确认未知时保留原资源保护。本机 AI 和远程的 network.rename 权限未扩大。",
              "Qt失败轮次续跑以原PowerTestResumeSession判定通道资格。aging.qt_resume.confirm仅限本机逐条确认。运行中复用原批次，结束后按确认顺序逐条复核并由aging.resume任务取得原通道资源。安全停止或关闭时取消等待项，等待项不自动恢复。沿用原提交、版本预检、控制队列和停止服务。保留原批次结论及其他通道进度。",
              "Qt六标签配置编辑复用TestItemConfigStore、LegacyUiDefaultsStore、MessagePushConfigService和原项目版本保存；configuration.editor.*仅gui来源，私有字段不返回AI/远程。保存复核版本与任务占用。预备测试使用本机pretest.editor.*确认的当前测试项和Telnet草稿，经原Job和单次服务执行，关闭先停并等待收尾。version.editor.*绑定单一通道和当前Telnet草稿，经原Job及样机版本服务查询，只读显示。notifications.editor.*仅供本机确认当前Webhook、广播选项和已保存项目名后，经原服务单次试发；不授予AI或远程草稿发送权限。",
              "Qt六标签页面恢复草稿由本机configuration.editor.checkpoint保存，按项目和版本加密。恢复或清除需本机选择。恢复只回填窗口，沿用现有保存校验和准入。",
              "Qt通道编辑通过channels.editor.*仅gui来源预览/确认，数据投影复用原ChannelCapabilities.prepare/commit及ChannelConfigStore，仍只写已选通道；补齐16槽位不代表设备正在运行。主工具栏和通道编辑器共用本机只读串口/网卡枚举，串行读取独立于项目控制队列，保留选择和失败来源的上次清单。工作区空闲时核对身份登记，活动租约由原任务和准入服务维护。常规保存只提交授权范围内的配置；矩阵/列表共用实际快照。",
              "Qt串口窗口通过serial.terminal.*仅gui来源共享原SerialSessionManager/PySerialSession：显示不打开COM，监控/手动发送/停止由后台执行，危险命令本机确认；关闭只释放自己的所有权，升级控制锁及实际收尾保护保留。显示缓冲有界，原日志独立落盘。诊断快照通过serial.terminal.diagnostics读取原会话的近期接收数据及程序内占用状态。升级和写参串口路径已接入本机自动只读观察，模型会话实时串口联动待接入。",
              "Qt 串口和 DUT 的窗口状态由当前项目的本机界面保存，复用原 UI 状态文件。包含尺寸、位置和 DUT 各页状态区高度。保存偏好不调用设备执行、AI 或远程控制能力。",
              "Qt 的全流程、测试项配置、样机升级、写样机参数、ONU 注册和通道重试历史沿用当前项目原 module_windows.json 的宽高记录。窗口偏好通过已有后台工作线程合并保存。",
              "Qt日志范围根据实际项目、完整Job ID和原结构化通道字段筛选。实时批次仅追加匹配行及移除超出显示上限的记录。导出由本机文件选择发起，使用触发时的筛选快照，只写入用户选定的新TXT，原日志、任务和AI访问范围保持。",
              "Qt 通道右键菜单打开开关机结果日志或本次 WiFi 日志。定位沿用 latest_power_test_result_log / current_wifi_log，只将已校验的项目日志路径交给 Windows 文件关联。本机打开动作不授予 AI 或远程桌面操作能力，日志读取仍由原受控入口处理。",
              "Qt 通道详情和右键菜单允许本机分页查看当前开关机批次的原重试/失败事件及续跑记录。按项目、任务和授权通道绑定，只读任务库，沿用原业务状态和原因。",
              "Qt 任务历史的批次结果文件仅供本机操作员。使用原任务库、项目运行快照和原通道范围定位，浏览不读取正文，打开交给 Windows 文件关联。历史 WiFi 文件保持所选批次归属，不登记为当前尝试或扩大 AI / 远程权限。",
              "Qt任务历史通过本机只读窗口预筛当前页，并可按通道、级别、关键词查询选定项目的完整任务事件。按匹配记录分页，导出只写用户选定的新TXT。",
              "Qt 项目和设置菜单的多实例接入状态复用 remote.instances.status 的 RemoteInstanceManagement.status 只读服务。打开或刷新只读取当前状态。",
              "Qt 下次启动配置属于本机人工控制面。槽位和已保存的范围由原 RemoteInstanceManagement 读取。操作员明确选择通道与业务能力后，使用当前项目实际注册的远程能力复核，并由原服务保存待重启配置。",
              "Qt 项目和设置菜单共用 projects.remote_scope 本机人工控制面。按完整项目 ID 显示新增和撤销，以默认取消确认；后台复核已打开项目身份及原范围后调用 WorkspaceService.set_remote_projects。AI 和平台没有授权编辑入口。",
              "Qt归档日志是本机人工阅读入口。工作区原文、当前项目串口、主执行日志和资源监测文件按页只读。筛选导出沿用现有本机保存方式，不授予 AI 或远程访问。",
              "Qt系统状态面板只读展示工作区响应、日志写入、显示积压、任务日志和现有资源租约。展开与收起只影响显示，不新增业务能力。",
                "Qt DUT六页通过dut.editor.*仅gui来源接入原查询/配置服务和任务资源管理。本机确认、版本/NIC/查询绑定与安全停止统一；私有字段只供本机回填，任务结果和日志隐藏密码。WiFi原能力/SSID递增/双频/60秒等待、语音线路/编码顺序、TR069能力过滤和手动Inform均沿用原服务。真实设备验收另列。",
                "Qt样机升级通过firmware.editor.*本机界面控制，任务和执行仍使用firmware.upgrade和原四套引擎。项目升级选项沿用原配置文件和项目版本，编辑凭据仅在本机GUI回填。固件哈希、网卡、安全停止及只读串口观察使用原任务链。缺少程控电源时由Qt本机确认已手动重启；通用能力参数和原远程准入保持。",
                "Qt写样机参数通过parameters.editor.*本机入口，沿用原参数表预检、生成、受控parameters.write任务及停止。表格、目标及项目版本绑定于本机确认；本机选定路径另存和项目凭据保持本地，外部来源的文件输出与写参范围不扩大。DUT 和写参共用当前项目的本机登录草稿，凭据走原写参显式保存，仅本机显示。串口路径沿原回调，使用和升级共用的只读观察逻辑。Telnet仍使用任务文本日志。",
                "Qt ONU 通过onu.editor.*本机入口接入双型号配置、查询、注册、当前PON精确删除及独立保存OLT启动配置。C300单台注册的可选离线清理先只读查询，临时确认绑定本次候选接口和SN，执行由原服务复核仍离线及身份后仅重试一次。保存按原双型号策略，权限绑定原操作和整台OLT，任务结果可独立核对。",
                "AI及其余未迁移控制面仍待实施；本表connected表示既有共享后端能力，不表示所有Qt页面已完成。独立Qt原生验证使用scripts/verify_qt_migration.py，原Tk完整基线不能代替该验证。", ""]
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
