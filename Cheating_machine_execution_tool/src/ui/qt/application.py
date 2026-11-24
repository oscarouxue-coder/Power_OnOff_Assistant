"""Qt demo and real workspace launchers."""
from pathlib import Path
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox
from src.ui.qt.demo_data import logs, projects
from src.ui.qt.main_window import MainWindow
from src.ui.qt.theme import apply_theme


def runtime_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[3]


class FormWheelFilter(QObject):
    def eventFilter(self, target, event):
        if event.type() == QEvent.Type.Wheel and isinstance(target, (QComboBox, QAbstractSpinBox)):
            # Skipping the editor's handler lets Qt propagate to its scroll area.
            event.ignore()
            return True
        return False


def _create_application():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    app.installEventFilter(FormWheelFilter(app))
    app.setApplicationName('DUTPilot')
    app.setApplicationVersion('1.3.0')
    assets = Path(getattr(sys, '_MEIPASS', runtime_root()))
    app.setWindowIcon(QIcon(str(assets / 'assets/icons/DUTPilot-01.ico')))
    apply_theme(app)
    return app


def run_demo():
    app = _create_application()
    window = MainWindow(projects(), logs(), demo=True)
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1600, int(available.width() * .94)), min(900, int(available.height() * .92)))
    window.show()
    return app.exec()


def run_showcase():
    from src.ui.qt.component_showcase import ComponentShowcase

    app = _create_application()
    window = ComponentShowcase()
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1140, int(available.width() * .94)), min(840, int(available.height() * .92)))
    window.show()
    return app.exec()


def run_visual_preview():
    from src.ui.qt.visual_preview import VisualPreview

    app = _create_application()
    window = VisualPreview()
    available = app.primaryScreen().availableGeometry()
    window.resize(min(1440, int(available.width() * .94)), min(900, int(available.height() * .92)))
    window.show()
    return app.exec()


def run_workspace(project_path=None):
    import queue
    from src.core.workspace_instance import WorkspaceInstance
    from src.services.workspace_service import workspace_data_dir
    from src.ui.qt.workspace_controller import WorkspaceController
    source_root = runtime_root()
    instance = WorkspaceInstance(workspace_data_dir())
    restart = None
    try:
        if not instance.start(project_path):
            return 0
        app = _create_application()
        window = MainWindow(demo=False)
        controller = WorkspaceController(window, source_root, start_configured_gateway=True)
        source_arguments = tuple(sys.argv[1:])
        source_cwd = Path.cwd()
        if project_path:
            pending = [project_path]
            def open_initial():
                if controller.ready and pending:
                    controller.open_project(pending.pop())
            controller.timer.timeout.connect(open_initial)
        # Keep the original authenticated single-instance queue alive; opening
        # a project is a file command, never a request to replay its tests.
        def forwarded():
            if not controller.ready or controller.closing:
                return
            for _ in range(10):
                try:
                    request = instance.requests.get_nowait()
                except queue.Empty:
                    break
                if request['project']:
                    controller.open_project(request['project'])
                window.showNormal()
                window.raise_()
        controller.timer.timeout.connect(forwarded)
        available = app.primaryScreen().availableGeometry()
        window.resize(min(1600, int(available.width() * .94)), min(900, int(available.height() * .92)))
        window.show()
        result = app.exec()
        if not controller.adapter.wait_closed(5):
            raise RuntimeError('项目文件操作尚未结束，不能确认工作区已安全退出')
        if controller.feishu_repair.restart_requested:
            restart = (source_arguments, source_cwd)
    finally:
        instance.close()
    if restart is not None:
        from src.core.source_restart import launch_restart_helper, report_restart_failure
        try:
            launch_restart_helper(source_root, restart[0], cwd=str(restart[1]))
        except Exception:
            report_restart_failure()
    return result
