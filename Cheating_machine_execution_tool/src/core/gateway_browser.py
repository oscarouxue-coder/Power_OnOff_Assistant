"""Owned Chromium window for the gateway's Software update form (no driver dependency)."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil

from .gateway_cdp import DevToolsClient
from .gateway_proxy import GatewayProxy


def find_gateway_browser():
    for executable, suffix in (("msedge.exe", "Microsoft/Edge/Application/msedge.exe"),
                               ("chrome.exe", "Google/Chrome/Application/chrome.exe")):
        candidates = [shutil.which(executable)]
        candidates += [str(Path(root, suffix)) for root in
                       (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                        os.environ.get("LOCALAPPDATA")) if root]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
    raise RuntimeError("web打开网关需要本机安装 Microsoft Edge 或 Google Chrome。")


def browser_command(executable, profile, proxy_port, *, headless=False):
    args = [executable, f"--user-data-dir={profile}",
            f"--proxy-server=http://127.0.0.1:{proxy_port}", "--proxy-bypass-list=<-loopback>",
            "--disable-quic", "--disable-background-networking", "--disable-extensions",
            "--disable-sync", "--no-first-run", "--no-default-browser-check",
            "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]
    if headless:
        args.append("--headless=new")
    return args + ["about:blank"]


class GatewayBrowser:
    def __init__(self, source_ip, interface_index, target_ip, log, *, target_port=80, headless=False):
        self.proxy = GatewayProxy(source_ip, interface_index, target_ip, log, target_port)
        self.url = f"http://{target_ip}" + (f":{target_port}" if target_port != 80 else "") + "/"
        self.log = log
        self.headless = headless
        self.profile = None
        self.process = None
        self.process_identity = None
        self.cdp = None
        self.submitted = False

    def start(self):
        try:
            executable = find_gateway_browser()
            self.proxy.wait_for_gateway()
            port = self.proxy.start()
            self.profile = tempfile.TemporaryDirectory(prefix="linecheck-web-upgrade-")
            self.process = subprocess.Popen(
                browser_command(executable, self.profile.name, port, headless=self.headless),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.process_identity = psutil.Process(self.process.pid)
            deadline = time.monotonic() + 20
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("独立升级浏览器启动失败或已关闭。")
                try:
                    debug_port = int(Path(self.profile.name, "DevToolsActivePort").read_text().splitlines()[0])
                    with opener.open(f"http://127.0.0.1:{debug_port}/json/list", timeout=1) as response:
                        targets = json.load(response)
                    target = next(item for item in targets if item.get("type") == "page")
                except (OSError, ValueError, IndexError, StopIteration):
                    time.sleep(0.1)
                    continue
                self.cdp = DevToolsClient(target["webSocketDebuggerUrl"])
                break
            if self.cdp is None:
                raise TimeoutError("独立升级浏览器 DevTools 启动超时。")
            self.log(f"Web 浏览器已启动：{self.url}，出口 {self.proxy.source_ip} / ifIndex {self.proxy.interface_index}")
            # Network probing above is separate from the navigation response
            # budget, so a just-starting boot server no longer kills the batch
            # after the generic DevTools 15-second timeout.
            result = self.cdp.call("Page.navigate", {"url": self.url}, timeout=30)
            if result.get("errorText"):
                raise RuntimeError(f"打开网关失败：{result['errorText']}")
        except Exception:
            self.close()
            raise

    def submit_firmware(self, firmware_path, timeout=60):
        if self.submitted:
            raise RuntimeError("本通道已经点击 Update software，禁止重复提交。")
        firmware = Path(firmware_path).resolve(strict=True)
        if not firmware.is_file():
            raise ValueError("升级固件不是文件。")
        expected_origin = self.url.rstrip("/")
        # Store references only after identifying an unambiguous, visible form.
        locate = """(() => {
          if (location.origin !== ORIGIN) return false;
          const visible = e => e.getClientRects().length > 0 && !e.disabled;
          const files = [...document.querySelectorAll('input[type=file]')].filter(visible);
          if (files.length !== 1) return false;
          const file = files[0], root = file.form || document;
          const buttons = [...root.querySelectorAll('button,input[type=submit],input[type=button]')]
            .filter(e => visible(e) && (e.value || e.textContent).trim().toLowerCase() === 'update software');
          if (buttons.length !== 1) return false;
          if (file.form && new URL(file.form.action || location.href).origin !== ORIGIN)
            throw new Error('升级表单指向另一目标，已阻止提交');
          window.__linecheckUpgrade = {file, button: buttons[0]};
          return true;
        })()""".replace("ORIGIN", json.dumps(expected_origin))
        deadline = time.monotonic() + timeout
        while not self.cdp.evaluate(locate):
            if time.monotonic() >= deadline:
                raise TimeoutError("未找到唯一的升级文件框和 Update software 按钮，未提交升级。")
            time.sleep(0.25)
        self.log("Web 软件升级界面已打开，已识别文件选择框和 Update software。")
        node = self.cdp.call("Runtime.evaluate", {"expression": "window.__linecheckUpgrade.file"})
        object_id = node.get("result", {}).get("objectId")
        if not object_id:
            raise RuntimeError("无法定位升级文件选择框，未提交升级。")
        self.cdp.call("DOM.setFileInputFiles", {"objectId": object_id, "files": [str(firmware)]})
        selected = self.cdp.evaluate("(() => {const f=window.__linecheckUpgrade.file.files;"
                                     "return f.length===1 ? {name:f[0].name,size:f[0].size} : null;})()")
        if selected != {"name": firmware.name, "size": firmware.stat().st_size}:
            raise RuntimeError("网页固件文件选择校验失败，未点击 Update software。")
        self.log(f"Web 已选择固件：{firmware}（{selected['size']} 字节）")
        # Mark attempted before the command: a lost response must not cause a retry.
        self.submitted = True
        clicked = self.cdp.evaluate("(() => {const u=window.__linecheckUpgrade;"
                                    "if(!u || !u.file.isConnected || !u.button.isConnected || u.button.disabled)"
                                    "throw new Error('升级控件已失效');"
                                    "u.button.click(); return true;})()")
        if clicked is not True:
            raise RuntimeError("未确认 Update software 点击动作，停止后续流程。")
        self.log("Web 已点击 Update software（仅提交动作，不代表固件写入成功）。")

    def close(self):
        if self.cdp:
            try:
                self.cdp.call("Browser.close", timeout=2)
            except Exception:
                pass
            try:
                self.cdp.close()
            except OSError:
                pass
            self.cdp = None
        if self.process:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # Only the process tree belonging to our disposable profile.
                try:
                    descendants = self.process_identity.children(recursive=True)
                    for child in descendants:
                        try:
                            child.terminate()
                        except psutil.Error:
                            pass
                    self.process_identity.terminate()
                    _, alive = psutil.wait_procs(descendants + [self.process_identity], timeout=3)
                    for process in alive:
                        try:
                            process.kill()
                        except psutil.Error:
                            pass
                    psutil.wait_procs(alive, timeout=2)
                except psutil.Error as exc:
                    self.log(f"升级浏览器进程清理失败：{exc}")
            self.process = None
        self.proxy.close()
        if self.profile:
            try:
                self.profile.cleanup()
            except OSError as exc:
                self.log(f"升级浏览器临时目录清理失败：{exc}")
            self.profile = None
