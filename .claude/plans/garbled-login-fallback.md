# 串口乱码时的盲发密码补救登录

## 背景

真实样机日志（2026-07-12 19:40）显示 UART 输出损坏导致 boot 登录失败：

```
RX }                              ← 无意义字节
RX C�H�                           ← 乱码（包含 UTF-8 替换符）
RX U
RX serName:                       ← UserName: 被拆成 U + serName:
TX telecomadmin
RX  (0  $��                       ← 回显损坏
TX  (\r)
RX }                              ← Password: 也是乱码
RX C!���ݽɑ�
... 30 秒等待 Password: 超时 ...
```

UART 输出损坏但 UART 输入正常时，样机可能已经接受账号，但 `Password:` 提示符也是乱码。当前的 `_login_boot` 和 `login_tftp_put_boot_after_username` 都会等待 `Password:` 提示符，超时后只能重试或放弃。

本次需求：用户名回车后若检测到乱码（U+FFFD），盲发密码一次。如果样机已接受账号，密码后能进入 shell 提示符（`#` / `>` / `ecnt>` / `u-boot>`），即可视为登录成功。

## 设计原则

- 保持 `Tftp指令` 和 `Tftp Put` 两条链路独立，本次改动**仅新增对称的 salvage 分支**，不合并两条流程。
- 不改动已验收时序：完整 `UserName:` / `Password:` 提示符到达时仍走原路径，salvage 只在超时且乱码时触发。
- 不动 `build/`、`dist/`、`logs/`、`.venv/`，不自动 commit。

## 实现方案

### 1. 新增会话诊断能力

**文件**：`src/core/serial_transport.py`

在 `PySerialSession` 上新增方法，从指定游标读取到当前的全部历史文本（不解码消费）：

```python
def peek_since(self, cursor: int) -> str:
    """从指定游标读取到当前的全部历史数据的解码字符串。

    用于诊断（如检测 UTF-8 解码失败标记），不消费也不修改历史。
    """
    with self._condition:
        data = bytes(self._history[cursor:])
    return self._display(data)
```

线程安全：与 `wait_for_any` 一样持有 `_condition` 锁后读取 `_history` 的副本。

### 2. 乱码判定工具

**文件**：`src/services/serial_upgrade_service.py`

模块顶部新增常量和辅助函数：

```python
GARBLED_REPLACEMENT_MARKER = "�"  # _display() 中 decode(errors="replace") 的替换符


def _looks_like_garbled_response(text: str) -> bool:
    """粗略判断：响应中包含 UTF-8 解码失败标记即视为乱码。"""
    return bool(text) and GARBLED_REPLACEMENT_MARKER in text
```

### 3. 共享的 salvage 方法

**文件**：`src/services/serial_upgrade_service.py`

在 `SerialUpgradeController` 上新增 `_try_login_after_garbled_username`，被两条登录路径复用：

```python
GARBLED_LOGIN_RESULT_PROMPTS = ("#", ">", "ecnt>", "u-boot>")


def _try_login_after_garbled_username(self, password_cursor: int) -> CommandResult:
    """用户名回显异常时盲发一次密码,验证样机是否已接受账号。

    适用场景:UART 输出损坏导致 Password: 提示符也是乱码,但 UART 输入正常。
    如果样机实际已接受账号,密码后应进入 shell 提示符。
    """
    self.session.write(BOOT_PASSWORD.encode("utf-8"), sensitive=True)
    self.sleep(1.0)
    self.session.write(b"\r", sensitive=True)
    result_cursor = self.session.cursor()
    result = self.session.wait_for_any(GARBLED_LOGIN_RESULT_PROMPTS, 12, result_cursor)
    if result in GARBLED_LOGIN_RESULT_PROMPTS:
        return CommandResult(
            True,
            f"用户名回显乱码，盲发密码后检测到 shell 提示符 {result!r}。",
        )
    return CommandResult(False, "用户名回显乱码，盲发密码未检测到 shell 提示符。")
```

### 4. 修改 `_login_boot`（Tftp指令）

**文件**：`src/services/serial_upgrade_service.py` 第 162 行附近

`Password:` 超时分支前增加 salvage 尝试：

```python
password_prompt = self.session.wait_for_any(BOOT_PASSWORD_PROMPTS, 30, password_cursor)
if password_prompt not in BOOT_PASSWORD_PROMPTS:
    # 现场: UART 输出损坏导致 Password: 提示符也是乱码;UART 输入正常。
    # 若用户名回显含有 UTF-8 替换标记,盲发密码一次验证登录。
    recent_text = self.session.peek_since(password_cursor)
    if recent_text and _looks_like_garbled_response(recent_text):
        salvage = self._try_login_after_garbled_username(password_cursor)
        if salvage.ok:
            return salvage
    continue
```

salvage 失败不影响 `for _attempt in range(max_attempts)` 的常规重试。

### 5. 修改 `login_tftp_put_boot_after_username`（Tftp Put）

**文件**：`src/services/serial_upgrade_service.py` 第 219 行附近

Tftp Put 的 `Password:` 等待只有 10 秒且无内部重试，加同样的 salvage 分支：

```python
password_prompt = self.session.wait_for_any(BOOT_PASSWORD_PROMPTS, 10, password_cursor)
if password_prompt not in BOOT_PASSWORD_PROMPTS:
    # 现场: UART 输出损坏导致 Password: 提示符也是乱码;盲发密码一次验证登录。
    recent_text = self.session.peek_since(password_cursor)
    if recent_text and _looks_like_garbled_response(recent_text):
        salvage = self._try_login_after_garbled_username(password_cursor)
        if salvage.ok:
            return salvage
    return CommandResult(False, "boot 登录未检测到 Password 提示符。")
```

保持现有的"非乱码超时立即失败"行为，避免给正常路径引入额外延迟。

### 6. 测试

**文件**：`tests/test_serial_upgrade_service.py`、`tests/test_serial_transport.py`

`FakeSession` 增加 `peek_text` 字段与 `peek_since` 方法（默认返回 `peek_text`），与生产代码对称。

新增 / 调整用例：

| 用例 | 覆盖 |
| --- | --- |
| `test_login_boot_salvages_after_garbled_username_echo` | Tftp指令：用户名回显含 `�` → 盲发密码 → 命中 `>` → 成功 |
| `test_login_boot_garbled_salvage_without_shell_prompt_falls_through_to_retry` | Tftp指令：乱码 + 盲发密码后无 shell → continue 常规重试 |
| `test_login_boot_clean_timeout_does_not_salvage` | Tftp指令：超时但无乱码 → 不盲发（避免误伤） |
| `test_tftp_put_salvages_after_garbled_username_echo` | Tftp Put：乱码 → 盲发密码 → 命中 `ecnt>` → 成功 |
| `test_tftp_put_clean_timeout_still_fails_without_salvage` | Tftp Put：超时但无乱码 → 立即失败，无盲发 |
| `test_peek_since_returns_decoded_text_from_cursor` | `PySerialSession.peek_since` 基础行为 |

所有现有用例（特别是 `test_login_boot_rejects_password_received_before_username_submission`、`test_login_boot_waits_for_password_after_username_enter_using_fresh_cursor`、`test_tftp_put_boot_login_keeps_shell_cursor_before_password_write`）预期不受影响：它们的 `Password:` 在超时前就被命中，不走 salvage 分支。

### 7. 文档

**文件**：`DEVELOPMENT_LOG.md`、`PROJECT_STATUS.md`（如适用）

- `DEVELOPMENT_LOG.md` 顶部追加一条记录，按标准模板写清背景、改动、修改文件、验证方法和验证结果（单元测试）。
- 不动 `PROJECT_STATUS.md` 的进度表和约束（本次属于异常现场补强，不改变已验收时序，符合"不要预先改变已验收时序"的约束）。
- `line_check_assistant_README.md` 不需要改（这是内部异常处理，用户不可见）。

## 修改文件清单

- `Cheating_machine_execution_tool/src/core/serial_transport.py` — 新增 `peek_since`
- `Cheating_machine_execution_tool/src/services/serial_upgrade_service.py` — 新增 salvage 方法 + 改两条登录路径
- `Cheating_machine_execution_tool/tests/test_serial_transport.py` — 新增 `peek_since` 测试
- `Cheating_machine_execution_tool/tests/test_serial_upgrade_service.py` — 新增 / 调整 5 项用例 + `FakeSession.peek_since`
- `DEVELOPMENT_LOG.md` — 顶部追加记录

## 验证方法

```powershell
cd F:\Aouxue\Power_OnOff_Assistant\Cheating_machine_execution_tool
python -m py_compile src\core\serial_transport.py src\services\serial_upgrade_service.py
python -m unittest discover -s tests -v
```

预期 `Ran 159+ tests ... OK`（原 154 + 新增 ≥5 项）。

真实样机验证需要 UART 损坏的复现条件（线缆 / 电平 / 干扰），本次改动需配合现场排障时同步验证：
1. 同一根已知会让响应乱码的串口线
2. 触发 salvage：观察日志是否记录"用户名回显乱码，盲发密码后检测到 shell 提示符"
3. 触发不乱码：观察 salvage 不触发，原有时序保持

## 后续待办

- 真实 UART 损坏场景验证 salvage 命中率（依赖现场复现条件）
- 若新型号在乱码之外引入其他异常模式，再扩展超时 / 掉线 / 登录失败处理
