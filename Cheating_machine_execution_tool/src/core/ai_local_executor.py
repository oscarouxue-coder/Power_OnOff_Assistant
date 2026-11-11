"""本机命令和文件IO；不提升权限，仅清理本次进程树。"""
import base64
import difflib
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from line_check_assistant.subprocess_window import hidden_window_kwargs
from src.models.ai_actions import OUTPUT_LIMIT
from src.utils.ai_output import decode_pc_output


class WindowsProcessJob:
    """先以挂起态创建进程并加入Job，再恢复，确保子孙进程不会漏出清理范围。"""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum_ws", ctypes.c_size_t), ("maximum_ws", ctypes.c_size_t),
                        ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.resume = ctypes.WinDLL("ntdll").NtResumeProcess
        self.resume.argtypes, self.resume.restype = (wintypes.HANDLE,), ctypes.c_long
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def start(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            process.kill()
            process.wait(timeout=10)
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        if self.resume(int(process._handle)) != 0:
            self.terminate()
            raise RuntimeError("无法恢复本次PowerShell进程，未执行命令")

    def terminate(self):
        return bool(self.handle and self.kernel.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def file_snapshot(path):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "sha256": "", "size": 0}
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(65536), b""):
            digest.update(data)
            size += len(data)
    return {"exists": True, "sha256": digest.hexdigest(), "size": size}


def write_preview(path, content):
    before = file_snapshot(path)
    old = ""
    if before["exists"]:
        with Path(path).open("rb") as stream:
            old = decode_pc_output(stream.read(65536))[0]
    changes = "".join(difflib.unified_diff(old.splitlines(True), content[:65536].splitlines(True),
                                          fromfile=path, tofile=path + " (拟写入)"))
    return before, {"diff": changes[:65536], "preview_truncated": before["size"] > 65536 or len(content) > 65536 or len(changes) > 65536,
                    "new_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}


def read_local_file(path, offset_bytes=0, max_bytes=65536):
    with Path(path).open("rb") as stream:
        stream.seek(offset_bytes)
        data = stream.read(max_bytes + 1)
    text, encoding = decode_pc_output(data[:max_bytes])
    if "\x00" in text:
        raise ValueError("文件片段包含二进制数据，请通过命令工具按需处理")
    return {"path": path, "offset_bytes": offset_bytes, "bytes_read": min(len(data), max_bytes),
            "text": text, "encoding": encoding, "truncated": len(data) > max_bytes}


def write_local_file(path, content, before):
    if file_snapshot(path) != before:
        raise ValueError("文件自审查以来已变化，本次未写入；请重新读取、审查和确认")
    # 同目录原子替换，避免中断留下半份文件。
    descriptor, temporary = tempfile.mkstemp(prefix=".lca-ai-", dir=str(Path(path).parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if file_snapshot(path) != before:
            raise ValueError("文件在写入前发生变化，未覆盖")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": path, "bytes_written": len(content.encode("utf-8")), "sha256": file_snapshot(path)["sha256"]}


def terminate_process_tree(process, job=None):
    if job is not None:
        if not job.terminate():
            return False
    elif os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, timeout=10, **hidden_window_kwargs())
        if result.returncode and process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        return False
    return True


def run_local_command(command, cwd, timeout_seconds, stop, emit):
    if stop.is_set():
        raise InterruptedError("命令尚未下发，已取消")
    if os.name != "nt":
        raise RuntimeError("本机执行工具仅支持Windows PowerShell")
    prefix = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $OutputEncoding=[Console]::OutputEncoding;\n"
    encoded = base64.b64encode((prefix + command).encode("utf-16le")).decode("ascii")
    args = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    emit(f"[AI执行] PC TX（cwd={cwd}，超时={timeout_seconds}秒）：{command}")
    job = WindowsProcessJob()
    options = hidden_window_kwargs()
    options["creationflags"] = options.get("creationflags", 0) | 4  # CREATE_SUSPENDED
    try:
        process = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, **options)
        job.start(process)
    except BaseException:
        job.close()
        raise
    buffers = [bytearray(), bytearray()]
    counts = [0, 0]
    def drain(stream, index):
        try:
            while True:
                data = stream.read(8192)
                if not data:
                    break
                counts[index] += len(data)
                buffers[index].extend(data[:max(0, OUTPUT_LIMIT - len(buffers[index]))])
        finally:
            stream.close()
    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    deadline, status, cleaned = time.monotonic() + timeout_seconds, "completed", True
    try:
        while process.poll() is None:
            if stop.is_set() or time.monotonic() >= deadline:
                status = "cancelled" if stop.is_set() else "timed_out"
                cleaned = terminate_process_tree(process, job)
                break
            stop.wait(.05)
        # 父进程可能先退出而子进程仍持有输出管道；仍按同一截止时间清理。
        while any(reader.is_alive() for reader in readers):
            if stop.is_set() or time.monotonic() >= deadline:
                status = "cancelled" if stop.is_set() else "timed_out"
                cleaned = terminate_process_tree(process, job)
                break
            stop.wait(.05)
    except BaseException:
        terminate_process_tree(process, job)
        job.close()
        raise
    job.close()  # 正常结束也不遗留本次创建的后台子进程。
    for reader in readers:
        reader.join(2)
    stdout, stdout_encoding = decode_pc_output(bytes(buffers[0]))
    stderr, stderr_encoding = decode_pc_output(bytes(buffers[1]))
    return {"status": status, "exit_code": process.poll(), "stdout": stdout, "stderr": stderr,
            "stdout_encoding": stdout_encoding, "stderr_encoding": stderr_encoding,
            "truncated": any(n > OUTPUT_LIMIT for n in counts), "process_cleanup_confirmed": cleaned and not any(r.is_alive() for r in readers),
            "notice": "停止/超时只清理本次进程，不代表其已产生的系统或设备变更已回滚"}
