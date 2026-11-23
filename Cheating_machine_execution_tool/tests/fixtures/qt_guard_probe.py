"""Positive and swallowed-negative probes for the private-desktop Qt adapter."""
from importlib import import_module
import sys
import threading
from PySide6 import QtWidgets
from qt_test_guard import QtTestScope


def main():
    mode = sys.argv[1]
    if mode in ('tkinter', '_tkinter'):
        try:
            import_module(mode)
        except AssertionError as error:
            print('EXPECTED_QT_REJECTION', error)
        return
    if mode == 'missing':
        try:
            getattr(QtWidgets, 'Q' + 'Application')([])
        except AssertionError as error:
            print('EXPECTED_QT_REJECTION', error)
        return
    with QtTestScope() as scope:
        if mode == 'managed':
            assert 'tkinter' not in sys.modules and '_tkinter' not in sys.modules
            window = QtWidgets.QWidget()
            window.resize(360, 200)
            window.show()
            scope.app.processEvents()
            assert window.isVisible()
            assert window.windowHandle().isExposed()
            print('QT_NATIVE_WIDGET_MAPPED')
            return
        def invalid():
            try:
                if mode == 'dialog':
                    QtWidgets.QMessageBox.information(None, 'test', 'test')
                else:
                    getattr(QtWidgets, 'Q' + 'Widget')()
            except AssertionError as error:
                print('EXPECTED_QT_REJECTION', error)
        if mode == 'thread':
            worker = threading.Thread(target=invalid)
            worker.start()
            worker.join(3)
            assert not worker.is_alive()
        else:
            invalid()


if __name__ == '__main__':
    main()
