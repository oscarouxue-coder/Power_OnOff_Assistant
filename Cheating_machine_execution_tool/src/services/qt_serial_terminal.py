"""GUI-only serial terminal control over the unchanged shared serial manager."""
from datetime import date, datetime
from pathlib import Path
import json
import os
import queue
import time
import uuid

from src.core.serial_transport import SerialCloseStartError, vlan_to_serial_port
from src.models.capabilities import CapabilityError, CapabilitySpec, fingerprint, object_schema
from src.models.serial_delivery import SerialDelivery
from src.models.serial_models import SerialEvent, SerialSettings
from src.services.ai_serial_client import read_existing_serial
from src.utils.bounded_mailbox import BoundedMailbox


class DisplayDelivery(SerialDelivery):
    """Never retains an unbounded driver packet or any QWidget reference."""
    def __init__(self, vlan, mailbox):
        super().__init__(vlan, mailbox)
        self.trimmed = 0

    def __call__(self, event):
        if self.invalid.is_set():
            return
        text = event.text
        self.trimmed += max(0, len(text) - 16384)
        super().__call__(SerialEvent(event.port, event.direction, b'', text[-16384:], event.sensitive))


class QtSerialTerminal:
    def __init__(self, service, context):
        self.service, self.context, self.manager = service, context, service.manager
        self.token = ''
        self.tabs = {}
        self.last_open_errors = {}
        self.pending = None
        self.closing = False
        self.events = BoundedMailbox(2000)
        self.reported_drops = 0
        self.state_file = context.root / 'ui/serial.json'
        self.log_dir = context.root / 'logs/serial'
        self._restored = False
        token = dict(type='string', minLength=32, maxLength=32)
        target = dict(type='string', minLength=1, maxLength=200)
        schemas = {
            'show': object_schema(),
            'diagnostics': object_schema({'token': token, 'target': target, 'port': target},
                                         ('token', 'target', 'port')),
            'poll': object_schema({'token': token, 'active': dict(type='string', maxLength=200)}, ('token', 'active')),
            'open_all': object_schema({'token': token}, ('token',)),
            'stop_all': object_schema({'token': token}, ('token',)),
            'detach': object_schema({'token': token}, ('token',)),
            'close_tab': object_schema({'token': token, 'target': target}, ('token', 'target')),
            'preview_send': object_schema({'token': token, 'target': target,
                'text': dict(type='string', maxLength=4096)}, ('token', 'target', 'text')),
            'send': object_schema({'token': token, 'confirmation': token}, ('token', 'confirmation')),
            'cancel': object_schema({'token': token, 'target': dict(type='string', maxLength=200)}, ('token',)),
            'folder': object_schema({'token': token}, ('token',)),
            'directory': object_schema({'token': token, 'path': dict(type='string', minLength=1, maxLength=2048)}, ('token', 'path')),
        }
        for suffix, schema in schemas.items():
            service.registry.register(CapabilitySpec('serial.terminal.' + suffix, '本机串口终端 ' + suffix,
                '仅供本机GUI串口窗口；共享原会话和资源保护，不授予AI/远程任意字符发送权限。', schema,
                getattr(self, suffix), risk=('dangerous' if suffix == 'send' else
                    'read' if suffix in ('show', 'poll', 'cancel', 'diagnostics') else 'modify'),
                sources=('gui',)))

    def _log(self, text):
        self.service.emit('[Qt串口] ' + text)

    def _guard(self, arguments, *, allow_closing=False):
        if not self.token or arguments.get('token') != self.token:
            raise CapabilityError('terminal_expired', '串口窗口上下文已失效，请重新打开')
        if self.closing and not allow_closing:
            raise CapabilityError('terminal_closing', '串口正在停止并保存日志，请等待')

    def _targets(self):
        return [c for c in self.service.snapshot()['channels'] if c.get('enabled') and c.get('vlan_name')]

    def _binding(self):
        return fingerprint(self.service.snapshot()['channels'])

    def log_directory(self):
        if not self._restored:
            state = self._load_state()
            try:
                saved = state.get('log_dir')
                if isinstance(saved, str) and saved and Path(saved).is_dir():
                    self.log_dir = Path(saved)
            except (OSError, ValueError):
                pass
            self._restored = True
        return self.log_dir

    def _ensure_window(self):
        if self.closing:
            raise CapabilityError('terminal_closing', '串口窗口正在收尾')
        self.log_directory()
        if not self.token:
            self.token = uuid.uuid4().hex

    def _target_tab(self, vlan, port):
        item = self.tabs.get(vlan)
        if item is None:
            item = self.tabs[vlan] = dict(port=port, session=None, owner=None, delivery=None, ticket=None,
                state='未打开', error=False, path='', pending='', dropped=0, remove=False)
        elif item['session'] is None and item['ticket'] is None and not item['error']:
            item['port'] = port
        return item

    def show(self, arguments, authority):
        self._ensure_window()
        for channel in self._targets():
            vlan = channel['vlan_name'].lower()
            port = (channel.get('serial_port') or vlan_to_serial_port(vlan)).strip().upper()
            self._target_tab(vlan, port)
        self._log('已显示当前已选通道；本次显示未打开新串口或发送字符')
        return self.poll(dict(token=self.token, active=''), authority)

    def open_pipeline(self, channels, directory):
        self._ensure_window()
        if directory != self.log_dir:
            raise CapabilityError('configuration_changed', '确认后串口日志目录已变化')
        failures = []
        for channel in channels:
            vlan = channel.vlan_name.lower()
            item = None
            try:
                port = (channel.serial_port or vlan_to_serial_port(vlan)).strip().upper()
                item = self._target_tab(vlan, port)
                if item['port'] != port:
                    raise CapabilityError('configuration_changed', '已打开的串口与本次通道映射不一致')
                self._open(vlan, item)
            except Exception as error:
                if item is not None and item['session'] is None and item['ticket'] is None and not item['error']:
                    item['state'] = '打开失败：' + str(error)
                failures.append(vlan or channel.section)
                self._log('全流程串口预启动失败 ' + failures[-1] + '：' + str(error))
        self._log(f'全流程串口预启动完成，成功 {len(channels) - len(failures)} 项，失败 {len(failures)} 项')
        return failures

    def _open(self, vlan, item):
        if item['session'] is not None:
            return
        if item['ticket'] is not None or item['error']:
            raise CapabilityError('serial_closing', '串口正在收尾或关闭失败，须先核实')
        try:
            self._open_monitor(vlan, item)
        except Exception as error:
            self.last_open_errors[item['port']] = str(error)
            raise
        self.last_open_errors.pop(item['port'], None)

    def _open_monitor(self, vlan, item):
        owner = 'qt-terminal:' + self.token + ':' + vlan
        path = self.log_dir / f"{vlan}_{item['port']}_{date.today():%Y%m%d}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Reject an unwritable destination before touching the serial driver.
        with path.open('a', encoding='utf-8'):
            pass
        settings = SerialSettings(item['port'])
        # The original manager reuses an existing session with its actual
        # settings; a monitor must never reconfigure another owner's port.
        session = self.manager.acquire_monitor(owner, settings, path)
        delivery = DisplayDelivery(vlan, self.events)
        try:
            from src.core.transport_observation import label_session
            label_session(session, vlan=vlan)
            session.subscribe(delivery)
        except Exception:
            delivery.invalidate()
            self.manager.release(owner, item['port'], wait=True)
            raise
        item.update(session=session, owner=owner, delivery=delivery,
                    state='监控中' if session.log_path else '监控中（共享会话未启用文件落盘）',
                    path=str(session.log_path) if session.log_path else '', pending='')
        self._log('已打开监控 ' + vlan + ' / ' + item['port'] +
                  ('；日志：' + item['path'] if item['path'] else '；当前共享会话未启用文件落盘'))

    def diagnostics(self, arguments, authority):
        self._guard(arguments)
        target, port = arguments['target'], arguments['port']
        tab = self.tabs.get(target)
        if tab is None or tab['remove'] or tab['port'] != port:
            raise CapabilityError('target_changed', '串口标签或端口已变化，请重新选择')
        self._log(f'读取诊断快照 {target} / {port}')
        state = self.manager.diagnostic_state(port)
        power = self.service.snapshot().get('power_serial_port', '')
        state.update(last_open_error=self.last_open_errors.get(port, ''),
                     power_port_conflict=port == (power or '').strip().upper())
        try:
            text = read_existing_serial(self.manager, port)
        except RuntimeError as error:
            text = str(error)
            self._log(f'读取诊断数据失败 {target} / {port}：{error}')
        else:
            self._log(f'诊断快照完成 {target} / {port}' if state['opened_in_program']
                      else f'跳过串口数据读取 {target} / {port}：未打开')
        return dict(target=target, port=port, captured=datetime.now().astimezone().isoformat(timespec='seconds'),
                    state=state, text=text[-65536:])

    def open_all(self, arguments, authority):
        self._guard(arguments)
        failures = []
        for vlan, item in self.tabs.items():
            try:
                self._open(vlan, item)
            except Exception as error:
                item['state'] = '打开失败：' + str(error)
                failures.append(vlan)
                self._log(item['state'] + ' / ' + vlan + ' / ' + item['port'])
        result = self.poll(dict(token=self.token, active=''), authority)
        result['failures'] = failures
        return result

    def _stop(self, vlan, item, *, remove=False):
        if item['error']:
            raise CapabilityError('serial_close_unknown', '串口关闭失败，须核实后再关闭窗口')
        previous_remove = item['remove']
        item['remove'] |= remove
        if item['ticket'] is not None:
            return
        delivery, session = item['delivery'], item['session']
        if delivery is not None:
            delivery.invalidate()
        if session is not None and delivery is not None:
            session.unsubscribe(delivery)
        if item['owner'] is not None:
            try:
                item['ticket'] = self.manager.release(item['owner'], item['port'], wait=False)
            except Exception as error:
                item['remove'] = previous_remove
                if session is not None:
                    replacement = DisplayDelivery(vlan, self.events)
                    item['delivery'] = replacement
                    session.subscribe(replacement)
                if isinstance(error, SerialCloseStartError):
                    message = f"{vlan} / {item['port']} 停止请求未受理，原监控继续。请重试。"
                    self._log(f'{message}（{type(error).__name__}）')
                    raise CapabilityError('serial_release_refused', message) from error
                self._log('停止监控失败 ' + vlan + ' / ' + item['port'])
                raise
        if delivery is not None:
            item['dropped'] += delivery.trimmed
        item.update(owner=None, session=None, delivery=None, state='正在停止并保存日志')
        self.pending = None
        self._log('请求停止本标签监控 ' + vlan + ' / ' + item['port'] + '；其他所有者保持')

    def stop_all(self, arguments, authority):
        self._guard(arguments)
        for vlan, item in self.tabs.items():
            self._stop(vlan, item)
        return self.poll(dict(token=self.token, active=''), authority)

    def close_tab(self, arguments, authority):
        self._guard(arguments)
        vlan = arguments['target']
        item = self.tabs.get(vlan)
        if item is None:
            raise CapabilityError('target_changed', '串口标签已变化')
        if not self.manager.manual_writable(item['port']):
            self._log('跳过关闭 ' + vlan + ' / ' + item['port'] + '：存在控制所有者')
            raise CapabilityError('serial_busy', '当前串口正在自动升级或受控操作，结束后可关闭')
        self._stop(vlan, item, remove=True)
        return self.poll(dict(token=self.token, active=''), authority)

    def detach(self, arguments, authority):
        self._guard(arguments)
        if any(not self.manager.manual_writable(t['port']) for t in self.tabs.values()):
            raise CapabilityError('serial_busy', '当前串口正在自动升级或受控操作，结束后可关闭')
        # Check all failures before releasing any owner.
        if any(t['error'] for t in self.tabs.values()):
            raise CapabilityError('serial_close_unknown', '存在关闭失败的串口，请先核实')
        try:
            self._save_state(self.log_dir)
        except OSError:
            self._log('日志目录设置未保存，继续等待串口日志收尾')
        for vlan, item in self.tabs.items():
            self._stop(vlan, item, remove=True)
        # A refused release leaves its monitor attached. Allow a new close
        # request while poll continues to settle the already accepted tickets.
        self.closing = True
        return self.poll(dict(token=self.token, active=''), authority)

    def preview_send(self, arguments, authority):
        self._guard(arguments)
        self.pending = None
        item = self.tabs.get(arguments['target'])
        if item is None:
            raise CapabilityError('target_changed', '串口标签已关闭，请重新选择')
        # Original manual Send opens its monitor first, including an empty CR.
        self._open(arguments['target'], item)
        if not self.manager.manual_writable(item['port']):
            raise CapabilityError('serial_busy', '当前串口正在受控操作，只允许查看输出')
        text = arguments['text']
        dangerous = any(word in text.lower() for word in ('reboot', 'reset', 'firstboot', 'tftp', 'upgrade'))
        token = uuid.uuid4().hex
        self.pending = dict(token=token, created=time.monotonic(), binding=self._binding(),
            target=arguments['target'], item=item, delivery=item['delivery'], text=text)
        return dict(confirmation=token, dangerous=dangerous,
            summary=self.context.identity.name + '\n' + arguments['target'] + ' / ' + item['port'] +
                '\n将发送：' + (text or '空回车') + '\n是否继续？')

    def send(self, arguments, authority):
        self._guard(arguments)
        pending, self.pending = self.pending, None
        if not pending or pending['token'] != arguments['confirmation'] or time.monotonic() - pending['created'] > 120:
            raise CapabilityError('confirmation_expired', '发送确认已失效，未发送')
        item = self.tabs.get(pending['target'])
        if item is not pending['item'] or item['delivery'] is not pending['delivery'] or item['session'] is None or self._binding() != pending['binding']:
            raise CapabilityError('target_changed', '串口或通道绑定已变化，未发送')
        if not self.manager.manual_writable(item['port']):
            raise CapabilityError('serial_busy', '当前串口正在受控操作，未发送')
        owner = 'qt-manual:' + uuid.uuid4().hex
        session = self.manager.acquire_existing_control(owner, item['session'].settings)
        try:
            self._log('实际发送 ' + pending['target'] + ' / ' + item['port'] + '：' + repr(pending['text']) + ' + 回车')
            session.send_line(pending['text'])
        except Exception:
            self._log('发送失败 ' + item['port'] + '；不自动重发')
            raise
        finally:
            self.manager.release(owner, item['port'], wait=True)
        self._log('发送完成 ' + item['port'])
        return dict(sent=True)

    def cancel(self, arguments, authority):
        self._guard(arguments)
        self.pending = None
        self._log('本机取消关闭标签：' + arguments['target'] if arguments.get('target') else '本机取消发送；未发送字符')
        return dict(cancelled=True)

    def folder(self, arguments, authority):
        self._guard(arguments)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.log_dir))
        self._log('已打开日志目录：' + str(self.log_dir))
        return dict(opened=True)

    def _load_state(self):
        try:
            value = json.loads(self.state_file.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self, directory):
        value = self._load_state()
        value['log_dir'] = str(directory)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_name('serial.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(self.state_file)
        finally:
            temporary.unlink(missing_ok=True)

    def directory(self, arguments, authority):
        self._guard(arguments)
        directory = Path(arguments['path']).resolve()
        if directory.name != self.context.identity.project_id:
            directory /= self.context.identity.project_id
        directory.mkdir(parents=True, exist_ok=True)
        self._save_state(directory)
        self.log_dir = directory
        self._log('新打开的监控使用目录：' + str(directory) + '；已有会话不迁移文件')
        return dict(log_dir=str(directory))

    def poll(self, arguments, authority):
        self._guard(arguments, allow_closing=True)
        deadline = time.monotonic() + .01
        for _ in range(120):
            if time.monotonic() >= deadline:
                break
            try:
                vlan, event, delivery = self.events.get_nowait()
            except queue.Empty:
                break
            item = self.tabs.get(vlan)
            if item is None or item['delivery'] is not delivery:
                continue
            combined = item['pending'] + event.text
            item['dropped'] += max(0, len(combined) - 65536)
            item['pending'] = combined[-65536:]
        for vlan, item in tuple(self.tabs.items()):
            ticket = item['ticket']
            if ticket is not None and not ticket.done.is_set():
                continue
            if ticket is not None and ticket.error:
                if not item['error']:
                    self._log('关闭失败 ' + vlan + ' / ' + item['port'] + '：' + ticket.error)
                item.update(error=True, state='关闭失败：' + ticket.error)
                self.closing = False
                continue
            if ticket is not None or item['state'] == '正在停止并保存日志':
                item.update(ticket=None, state='已停止')
                if item['remove']:
                    del self.tabs[vlan]
                    self._log('已关闭 ' + vlan + ' / ' + item['port'] + '；已保存日志保留')
            elif item['session'] is not None and item['session'].error is not None:
                state = '读取失败：' + str(item['session'].error)
                if item['state'] != state:
                    self._log(vlan + ' / ' + item['port'] + ' ' + state)
                item['state'] = state
        if self.events.dropped != self.reported_drops:
            self.reported_drops = self.events.dropped
            self._log('界面显示事件繁忙，累计跳过 ' + str(self.reported_drops) + ' 条；原串口日志独立落盘')
        items = []
        for vlan, item in self.tabs.items():
            delivery = item['delivery']
            active = vlan == arguments['active']
            items.append(dict(target=vlan, port=item['port'], state=item['state'], path=item['path'],
                monitoring=item['session'] is not None, closing=item['ticket'] is not None,
                writable=self.manager.manual_writable(item['port']), text=item['pending'] if active else '',
                dropped=item['dropped'] + (delivery.trimmed if delivery else 0)))
            if active:
                item['pending'] = ''
        if self.closing and not self.tabs:
            self.token = ''
            self.pending = None
            self.events.clear()
            self.closing = False
        return dict(token=self.token, project_id=self.context.identity.project_id,
            project_name=self.context.identity.name, log_dir=str(self.log_dir), tabs=items,
            closing=self.closing, dropped_events=self.events.dropped)

    def shutdown(self):
        """Project/application close after original business jobs have stopped."""
        self.pending = None
        for item in self.tabs.values():
            if item['delivery'] is not None:
                item['delivery'].invalidate()
                item['session'].unsubscribe(item['delivery'])
            if item['owner'] is not None:
                ticket = self.manager.release(item['owner'], item['port'], wait=True)
                item.update(owner=None, session=None, delivery=None, ticket=ticket)
            ticket = item['ticket']
            if ticket is not None:
                ticket.done.wait()
                if ticket.error:
                    raise CapabilityError('serial_close_unknown', '串口收尾失败，不能确认安全退出：' + ticket.error)
        self.tabs.clear()
        self.token = ''
        self.events.clear()
