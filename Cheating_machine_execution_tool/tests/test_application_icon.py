"""Application identity, non-fatal startup, resource paths and native inheritance."""
import ctypes
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import textwrap
import tkinter as tk
import unittest
from unittest.mock import Mock, call, patch

from src.ui import application_icon as icons


ROOT = Path(__file__).resolve().parents[1]


class ApplicationIconTests(unittest.TestCase):
    def test_source_path_is_independent_of_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="图标 source ") as directory:
            try:
                os.chdir(directory)
                with patch.object(icons.sys, "frozen", False, create=True):
                    path = icons.application_icon_path()
                self.assertEqual(path, ROOT / icons.ICON_RELATIVE_PATH)
                self.assertEqual(path.read_bytes()[:4], b"\x00\x00\x01\x00")
            finally:
                os.chdir(previous)

    def test_source_path_supports_relocated_chinese_and_space_directories(self):
        with tempfile.TemporaryDirectory(prefix="中文 工程 ") as directory:
            root = Path(directory).resolve()
            with patch.object(icons, "__file__", str(root / "src/ui/application_icon.py")), \
                    patch.object(icons.sys, "frozen", False, create=True):
                self.assertEqual(icons.application_icon_path(), root / icons.ICON_RELATIVE_PATH)

    def test_frozen_path_uses_extraction_directory_instead_of_executable_or_cwd(self):
        with tempfile.TemporaryDirectory(prefix="中文 解包 ") as directory:
            with patch.object(icons.sys, "frozen", True, create=True), \
                    patch.object(icons.sys, "_MEIPASS", directory, create=True):
                self.assertEqual(icons.application_icon_path(), Path(directory) / icons.ICON_RELATIVE_PATH)

    def test_missing_frozen_root_does_not_abort_startup(self):
        with patch.object(icons.sys, "platform", "win32"), \
                patch.object(icons, "application_icon_path", side_effect=AttributeError("_MEIPASS")):
            messages = icons.apply_application_icon(Mock())
        self.assertIn("加载失败", messages[0])

    def test_missing_icon_is_reported_without_using_a_historical_resource(self):
        window = Mock()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.ico"
            with patch.object(icons.sys, "platform", "win32"), \
                    patch.object(icons, "application_icon_path", return_value=missing):
                messages = icons.apply_application_icon(window)
        window.iconbitmap.assert_not_called()
        self.assertIn(str(missing), messages[0])
        self.assertIn("继续启动", messages[0])

    def test_damaged_resource_is_reported_without_applying_a_generic_file_icon(self):
        valid = icons.application_icon_path().read_bytes()
        for contents in (b"broken", valid[:6], valid[:-1]):
            with self.subTest(length=len(contents)), tempfile.TemporaryDirectory() as directory:
                icon = Path(directory) / "corrupt.ico"
                icon.write_bytes(contents)
                window = Mock()
                with patch.object(icons.sys, "platform", "win32"), \
                        patch.object(icons, "application_icon_path", return_value=icon):
                    messages = icons.apply_application_icon(window)
                window.iconbitmap.assert_not_called()
                self.assertIn("加载失败", messages[0])

    def test_icon_has_native_dib_frames_for_common_windows_dpi_sizes(self):
        data = icons.application_icon_path().read_bytes()
        frames = {}
        for index in range(struct.unpack_from("<H", data, 4)[0]):
            width, height, _, _, planes, bpp, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
            self.assertEqual(width, height)
            self.assertEqual((planes, bpp), (1, 32))
            frames[width or 256] = data[offset:offset + length]
        self.assertEqual(set(frames), {16, 20, 24, 32, 40, 48, 64, 96, 128, 256})
        for size, payload in frames.items():
            if size < 256:
                self.assertEqual(struct.unpack_from("<Iii", payload), (40, size, size * 2))
            else:
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))

    @unittest.skipUnless(sys.platform == "win32", "Windows System.Drawing export")
    def test_asset_export_reproduces_the_checked_in_icon_without_application_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="图标 导出 ") as directory:
            output = Path(directory) / "export.ico"
            result = subprocess.run([
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "scripts/create_application_icon.ps1"), "-OutputIco", str(output)],
                cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), icons.application_icon_path().read_bytes())

    def test_both_window_icons_are_set_without_binding_events_or_scheduling_callbacks(self):
        window = Mock()
        with patch.object(icons.sys, "platform", "win32"):
            messages = icons.apply_application_icon(window)
        path = str(icons.application_icon_path())
        self.assertEqual(window.mock_calls, [call.iconbitmap(bitmap=path), call.iconbitmap(default=path)])
        self.assertTrue(all("成功" in message for message in messages))

    def test_corrupt_icon_or_tk_error_does_not_abort_other_initialization(self):
        for effects in ([tk.TclError("bad ICO"), None], [None, tk.TclError("default failed")],
                        [tk.TclError("bad ICO"), tk.TclError("bad ICO")]):
            with self.subTest(effects=effects):
                window = Mock()
                window.iconbitmap.side_effect = effects
                with patch.object(icons.sys, "platform", "win32"):
                    messages = icons.apply_application_icon(window)
                self.assertEqual(window.iconbitmap.call_count, 2)
                self.assertEqual(len(messages), 2)
                self.assertTrue(any("失败" in message for message in messages))

    def test_taskbar_id_is_stable_and_uses_wide_string_and_hresult(self):
        shell = Mock()
        shell.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        with patch.object(icons.sys, "platform", "win32"), \
                patch.object(icons.ctypes, "WinDLL", return_value=shell, create=True):
            messages = icons.set_taskbar_application_id()
        setter = shell.SetCurrentProcessExplicitAppUserModelID
        setter.assert_called_once_with("Aouxue.LineCheckAssistant")
        self.assertEqual(setter.argtypes, [ctypes.c_wchar_p])
        self.assertIs(setter.restype, ctypes.c_long)
        self.assertIn("成功", messages[0])

    def test_windows_api_load_and_hresult_failures_are_nonfatal(self):
        shell = Mock()
        shell.SetCurrentProcessExplicitAppUserModelID.return_value = -2147467259
        for options, detail in (({"side_effect": OSError("shell unavailable")}, "shell unavailable"),
                                ({"return_value": shell}, "0x80004005")):
            with self.subTest(detail=detail), patch.object(icons.sys, "platform", "win32"), \
                    patch.object(icons.ctypes, "WinDLL", create=True, **options):
                messages = icons.set_taskbar_application_id()
            self.assertIn(detail, messages[0])
            self.assertIn("继续启动", messages[0])

    def test_other_platforms_skip_windows_only_operations(self):
        window = Mock()
        with patch.object(icons.sys, "platform", "linux"), \
                patch.object(icons.ctypes, "WinDLL", create=True) as loader:
            self.assertIn("跳过", icons.set_taskbar_application_id()[0])
            self.assertIn("跳过", icons.apply_application_icon(window)[0])
        loader.assert_not_called()
        window.iconbitmap.assert_not_called()

    def test_main_window_initializes_identity_before_tk_and_icon_immediately_after(self):
        from line_check_assistant.app import LineCheckAssistant
        events = []
        with patch("line_check_assistant.app.set_taskbar_application_id",
                   side_effect=lambda: events.append("id") or []), \
                patch.object(tk.Tk, "__init__", side_effect=lambda: events.append("tk")), \
                patch("line_check_assistant.app.apply_application_icon",
                      side_effect=lambda root: events.append("icon") or []), \
                patch.object(LineCheckAssistant, "title", side_effect=RuntimeError("stop before devices")):
            with self.assertRaisesRegex(RuntimeError, "stop before devices"):
                LineCheckAssistant()
        self.assertEqual(events, ["id", "tk", "icon"])

    @unittest.skipUnless(sys.platform == "win32", "Windows native icon inheritance")
    def test_native_windows_icons_in_timed_isolated_process(self):
        probe = textwrap.dedent(r'''
            import ctypes
            from ctypes import wintypes as w
            from pathlib import Path
            import sys
            import tkinter as tk
            from src.ui.application_icon import *
            sys.path.insert(0, str(Path.cwd() / 'tests'))
            from tk_test_windows import OffscreenTkWindows

            shell = ctypes.WinDLL('shell32')
            shell.GetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
            shell.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
            ole = ctypes.WinDLL('ole32')
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            user = ctypes.WinDLL('user32')
            user.GetParent.argtypes = [w.HWND]
            user.GetParent.restype = w.HWND
            user.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
            user.SendMessageW.restype = ctypes.c_void_p
            user.GetClassLongPtrW.argtypes = [w.HWND, ctypes.c_int]
            user.GetClassLongPtrW.restype = ctypes.c_void_p
            user.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
            user.LoadImageW.restype = w.HANDLE
            user.DestroyIcon.argtypes = [w.HICON]
            gdi = ctypes.WinDLL('gdi32')
            class BITMAP(ctypes.Structure):
                _fields_ = [('type', w.LONG), ('width', w.LONG), ('height', w.LONG),
                            ('width_bytes', w.LONG), ('planes', w.WORD), ('bpp', w.WORD), ('bits', ctypes.c_void_p)]
            class ICONINFO(ctypes.Structure):
                _fields_ = [('icon', w.BOOL), ('x', w.DWORD), ('y', w.DWORD),
                            ('mask', w.HBITMAP), ('color', w.HBITMAP)]
            user.GetIconInfo.argtypes = [w.HICON, ctypes.POINTER(ICONINFO)]
            gdi.GetObjectW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p]
            gdi.GetBitmapBits.argtypes = [w.HBITMAP, w.LONG, ctypes.c_void_p]
            gdi.DeleteObject.argtypes = [w.HANDLE]
            def pixels(handle):
                info = ICONINFO()
                assert user.GetIconInfo(handle, ctypes.byref(info))
                try:
                    values = []
                    size = None
                    for bitmap in (info.color, info.mask):
                        data = BITMAP()
                        assert gdi.GetObjectW(bitmap, ctypes.sizeof(data), ctypes.byref(data))
                        size = size or (data.width, data.height)
                        length = data.width_bytes * data.height
                        buffer = ctypes.create_string_buffer(length)
                        assert gdi.GetBitmapBits(bitmap, length, buffer) == length
                        values.append((data.width, data.height, data.bpp, buffer.raw))
                    return size, values
                finally:
                    gdi.DeleteObject(info.color)
                    gdi.DeleteObject(info.mask)

            assert all('成功' in msg for msg in set_taskbar_application_id())
            identity = ctypes.c_wchar_p()
            assert shell.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(identity)) == 0
            try:
                assert identity.value == APPLICATION_ID
            finally:
                ole.CoTaskMemFree(ctypes.cast(identity, ctypes.c_void_p))
            with OffscreenTkWindows() as guard:
                root = tk.Tk()
                existing = tk.Toplevel(root)
                bindings = root.bind(), root.bind_all(), root.tk.call('after', 'info')
                assert all('成功' in msg for msg in apply_application_icon(root))
                assert bindings == (root.bind(), root.bind_all(), root.tk.call('after', 'info'))
                child = tk.Toplevel(root)
                nested = tk.Toplevel(child)
                child.destroy()
                reopened = tk.Toplevel(root)
                nested = tk.Toplevel(reopened)
                root.update()
                count = 0
                for window in (root, existing, reopened, nested):
                    hwnd = user.GetParent(window.winfo_id())
                    for kind in (0, 1):  # title-bar small icon and large Alt+Tab icon
                        handle = user.SendMessageW(hwnd, 0x007F, kind, 0)
                        if not handle:  # inherited icons may be stored on Tk's window class
                            handle = user.GetClassLongPtrW(hwnd, -34 if kind == 0 else -14)
                        assert handle, (window, kind)
                        size, actual = pixels(handle)
                        expected = user.LoadImageW(None, str(application_icon_path()), 1, *size, 0x10)
                        assert expected
                        try:
                            assert actual == pixels(expected)[1], (window, kind)
                        finally:
                            user.DestroyIcon(expected)
                        count += 1
                # Initialization installs no callbacks; ordinary destruction leaves no timers.
                assert not root.tk.call('after', 'info')
                root.destroy()
            print('NATIVE_ICON_OK windows=4 small_and_large=8 identity=verified offscreen_violations=0')
        ''')
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", probe], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NATIVE_ICON_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
