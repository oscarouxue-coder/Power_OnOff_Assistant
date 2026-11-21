"""Render actual source widgets on the existing guarded private desktop."""
from contextlib import ExitStack
from pathlib import Path
import argparse
import ctypes
import json
import faulthandler
import runpy
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from tk_test_windows import OffscreenTkWindows
from src.services.workspace_service import WorkspaceService
from src.ui.project_workspace import ProjectWorkspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--size', default='1480x900')
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--projects', type=int, default=1)
    parser.add_argument('--channels', type=int, default=0)
    parser.add_argument('--parameter-writer', action='store_true')
    parser.add_argument('--onu-query', action='store_true')
    args = parser.parse_args()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    args.output.mkdir(parents=True, exist_ok=True)
    trace = (args.output / 'render-trace.txt').open('w', encoding='utf-8')
    faulthandler.dump_traceback_later(12, file=trace)
    def mark(text):
        trace.write(text + '\n')
        trace.flush()
    source = Path(__file__).resolve().parents[1]
    capture = runpy.run_path(str(source.parent / '.claude/plans/workspace-layout-preview.py'))['capture_client']
    with tempfile.TemporaryDirectory(prefix='dutpilot-visual-') as temporary, ExitStack() as stack:
        windows = stack.enter_context(OffscreenTkWindows())
        for name in ('list_adapter_display_names', 'list_prolific_ports', 'list_serial_port_names'):
            stack.enter_context(patch('line_check_assistant.app.' + name, return_value=[]))
        stack.enter_context(patch('line_check_assistant.app.LineCheckAssistant._show_startup_warnings'))
        stack.enter_context(patch('src.services.remote_instance_management.selected_gateway_slot', return_value=None))
        stack.enter_context(patch('src.services.transport_history_monitor.TransportHistoryMonitor'))
        service = WorkspaceService(source, Path(temporary) / 'workspace')
        mark('construct workspace')
        root = ProjectWorkspace(source, service=service)
        errors = []
        root.report_callback_exception = lambda kind, error, tb: errors.append(str(error))
        try:
            root.tk.call('tk', 'scaling', float(root.tk.call('tk', 'scaling')) * args.scale)
            root.geometry(args.size)
            views = []
            for number in range(args.projects):
                mark('construct project ' + str(number))
                context = service.projects.create(Path(temporary) / str(number), f'Source Preview {number + 1}')
                if args.onu_query:
                    from test_qt_onu_query import configure_onu
                    configure_onu(service, context)
                root._add_project(context)
                root.save_project()
                views.append(root.current_view())
            view = views[0]
            root.select_project(view.project_context.identity.project_id)
            for index, channel in enumerate(view.channels[:args.channels]):
                channel.enabled = True
                channel.vlan_name = f'VLAN{101 + index}'
                channel.serial_port = f'COM{index + 1}'
            view._rebuild_channel_config_rows()
            # Fixture data is only inside this isolated rendering process.
            view.power_test_channel_progresses = {n: (68 if n < 4 else 67, 100, 'SIMULATED') for n in range(1, 17)}
            view.power_test_channel_states = {n: ('running', 'SIMULATED') for n in range(1, 17)}
            view.power_test_resume_session = SimpleNamespace(request=SimpleNamespace(
                channels=tuple(SimpleNamespace(number=n) for n in range(1, 17))), is_recovering=False)
            view._render_power_test_channel_overview()
            mark('mainloop')
            root.after(250, root.quit)
            root.mainloop()
            mark('update detail')
            root.update()
            if args.onu_query:
                mark('capture original ONU query')
                with patch('socket.create_connection', side_effect=AssertionError('fixture cannot connect an OLT')):
                    view._open_onu_registration_module()
                    root.update()
                capture(view.onu_registration_window, args.output / 'onu-tk-before.png')
                if errors:
                    raise AssertionError(errors)
                windows.assert_offscreen()
                return
            if args.parameter_writer:
                mark('capture original parameter writer')
                from src.core.sample_parameter_table import save_parameter_records_xlsx
                from src.models.sample_parameter_models import SampleParameterRecord
                from test_sample_parameter_service import values
                table = Path(temporary) / 'synthetic-parameters.xlsx'
                save_parameter_records_xlsx(table, [
                    SampleParameterRecord(c.vlan_name, values(), number)
                    for number, c in enumerate(view.channels[:args.channels], 2)])
                view.parameter_initial_username_var.set('fixture-parameter-user')
                view.parameter_table_path_var.set(str(table))
                view._open_sample_parameter_writer()
                root.update()
                capture(view.parameter_writer_window, args.output / 'parameters-tk-before.png')
                if errors:
                    raise AssertionError(errors)
                windows.assert_offscreen()
                return
            mark('capture detail')
            suffix = f'{args.size}-{args.scale}-{args.projects}'
            capture(root, args.output / f'detail-{suffix}.png')
            view.workbench_panels.toggle_config()
            mark('update config')
            root.update()
            capture(root, args.output / f'config-{suffix}.png')
            root.show_dashboard()
            mark('update overview')
            root.update()
            capture(root, args.output / f'overview-{suffix}.png')
            root.select_project(view.project_context.identity.project_id)
            view._open_test_item_config()
            mark('update dialog')
            root.update()
            dialog = view.test_item_config_window
            capture(dialog, args.output / f'telnet-{suffix}.png')
            (args.output / f'geometry-{suffix}.json').write_text(json.dumps(dict(
                size=args.size, scale=args.scale, simulated=True, errors=errors,
                window=[root.winfo_width(), root.winfo_height()],
                config_canvas=[view.workbench_panels.config_canvas.winfo_width(),
                               view.workbench_panels.config_canvas.bbox('all')],
                log_height=view.log_text.winfo_height()), ensure_ascii=False, indent=2), encoding='utf-8')
            if errors:
                raise AssertionError(errors)
            windows.assert_offscreen()
        finally:
            for view in tuple(root.views.values()):
                view.power_test_resume_session = None
                view._on_app_close()
            deadline = time.monotonic() + 3
            while root.views and time.monotonic() < deadline:
                root.update()
                time.sleep(.02)
            service.begin_close()
            root.destroy()
            service.close()
            faulthandler.cancel_dump_traceback_later()
            trace.close()


if __name__ == '__main__':
    main()
