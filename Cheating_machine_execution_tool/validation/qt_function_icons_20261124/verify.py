"""Capture a named revision using the locked Qt interpreter and native test guard."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.gui_test_process import run_gui_child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'after', 'after-badge-removal'))
    phase = parser.parse_args().phase
    interpreter = Path(os.environ['LOCALAPPDATA']) / 'LineCheckAssistant/qt-dev-py39/Scripts/python.exe'
    output = HERE / phase
    output.mkdir(exist_ok=True)
    for scale in ('1', '1.25', '1.5'):
        with tempfile.TemporaryDirectory(prefix='dutpilot-function-icons-') as temp:
            env = dict(os.environ, TEMP=temp, TMP=temp, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM='windows',
                       PYTHONUTF8='1', DUTPILOT_FUNCTION_ICON_CAPTURE=str(output))
            tests = ['qt_function_icons_probe.FunctionIconTests.test_offline_pages']
            if phase == 'after-badge-removal':
                tests = ['qt_function_icons_probe.FunctionIconTests.' + name for name in (
                    'test_toolbar_brand_and_sidebar', 'test_native_window_inherits_01_application_icon',
                    'test_assembled_toolbar_menus_and_overflow')]
            elif phase == 'after':
                tests.extend(('qt_function_icons_probe.FunctionIconTests.test_actions_states_and_type_metadata',
                              'qt_function_icons_probe.FunctionIconTests.test_assembled_toolbar_menus_and_overflow',
                              'qt_visual_preview_probe.DashboardPriorityTests',
                              'qt_workbench_probe.QtWorkbenchTests.test_cards_table_search_and_navigation_share_identity',
                              'qt_workbench_probe.QtWorkbenchTests.test_overview_metrics_and_filter_follow_project_identity_and_latest_evidence'))
            result = run_gui_child([str(interpreter), str(ROOT / 'scripts/run_tests.py'), *tests, '-v'],
                                   framework='qt', native_render=True, cwd=str(ROOT), env=env,
                                   capture_output=True, text=True, encoding='utf-8', timeout=100)
            print(scale, result.stderr, flush=True)
            (output / f'checks-{scale}.txt').write_text(result.stderr, encoding='utf-8')
            (output / f'isolation-{scale}.json').write_text(
                json.dumps(result.offscreen_report, ensure_ascii=False, indent=2), encoding='utf-8')
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
