"""Local review of an original Windows adapter rename and affected project drafts."""
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import time
import uuid

from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.network_ops import adapter_alias_from_display
from src.models.capabilities import CapabilityError
from src.services.adapter_rename_service import (
    AdapterRenameService, synchronize_channel_adapter_names, validate_adapter_name,
)
from src.services.qt_channel_configuration import channel_slots


@dataclass
class DraftChange:
    project_id: str
    name: str
    store: ChannelConfigStore
    digest: str
    channels: list
    power: str
    sections: tuple

    @property
    def binding(self):
        return self.project_id, self.name, self.store.config_path, self.digest, self.sections


class QtAdapterRename:
    def __init__(self, workspace, guard, publish):
        self.workspace = workspace
        self.guard = guard
        self.publish = publish
        self.rename_service = AdapterRenameService()

    @staticmethod
    def _digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''

    def _stores(self):
        stores = {}
        for identifier, context in sorted(self.workspace.projects.opened.items()):
            self.workspace.projects._validate_paths(context)
            stores[identifier] = (context.identity.name, ChannelConfigStore(context.config_dir / 'network_card_ip.ini'))
        return stores

    def _changes(self, stores, origin, section, old, new):
        changes = []
        for identifier, (name, store) in stores.items():
            with store.transaction():
                before = self._digest(store.config_path)
                channels = channel_slots(store.load())
                power = store.load_power_serial_port()
                if self._digest(store.config_path) != before:
                    raise CapabilityError('configuration_changed', '读取时通道配置变化，请重新审阅')
            selected = section if identifier == origin else ''
            affected = tuple(c.section for c in channels if c.section == selected or old.casefold() in (
                adapter_alias_from_display(c.adapter_alias).casefold(), adapter_alias_from_display(c.vlan_name).casefold()))
            if affected:
                synchronize_channel_adapter_names(channels, selected, old, new)
                changes.append(DraftChange(identifier, name, store, before, channels, power, affected))
        return changes

    def _available(self, editor):
        self.guard(editor)
        reason = self.rename_service.availability()
        if reason:
            raise CapabilityError('rename_unavailable', reason)

    def prepare(self, editor, arguments):
        self._available(editor)
        if editor._revision() != arguments['revision']:
            raise CapabilityError('configuration_changed', '当前通道配置已变化，请重新加载')
        old = adapter_alias_from_display(arguments['old_name'])
        try:
            new = validate_adapter_name(arguments['new_name'])
            adapters = self.rename_service.reader()
        except Exception as error:
            raise CapabilityError('rename_preflight_failed', str(error)) from None
        matches = [row for row in adapters if row.alias.casefold() == old.casefold()]
        if (len(matches) != 1 or not matches[0].interface_guid or
                sum(row.interface_guid == matches[0].interface_guid for row in adapters) != 1):
            raise CapabilityError('adapter_identity_required', '原网卡不存在、身份为空或不唯一，请先刷新')
        if any(row.alias.casefold() == new.casefold() for row in adapters):
            raise CapabilityError('adapter_name_exists', '新网卡名称已存在')
        target = matches[0]
        origin = editor.context.identity.project_id
        section = 'channel_' + str(arguments['number'])
        changes = self._changes(self._stores(), origin, section, target.alias, new)
        if editor._revision() != arguments['revision']:
            raise CapabilityError('configuration_changed', '审阅期间通道配置变化，请重新加载')
        token = uuid.uuid4().hex
        review = dict(confirmation=token, revision=arguments['revision'], created=time.monotonic(), origin=origin,
                      section=section, old=target.alias, new=new, guid=target.interface_guid,
                      binding=tuple(change.binding for change in changes))
        summary = (f'{target.alias} → {new}\n接口 GUID：{target.interface_guid}\n\n'
                   '确认后将修改 Windows 网卡名称并同步以下项目的通道草稿：\n' +
                   '\n'.join(f'{change.name} · ' + '、'.join(change.sections) for change in changes) +
                   '\n\n按原规则持久化已选通道；受影响的项目须保存配置版本后再启动测试。是否执行？')
        editor.capabilities.emit('[网卡重命名] 已核对网卡身份与受影响的通道，等待本机确认')
        return review, dict(confirmation=token, summary=summary)

    def apply(self, editor, review):
        self._available(editor)
        resources = self.workspace.resources
        origin, old, new, guid = (review[key] for key in ('origin', 'old', 'new', 'guid'))
        owner = 'gui:' + origin + ':qt-adapter-rename:' + uuid.uuid4().hex
        stores = self._stores()
        emit = editor.capabilities.emit
        with ExitStack() as locks:
            for _, store in stores.values():
                locks.enter_context(store.transaction())
            if editor._revision() != review['revision']:
                raise CapabilityError('configuration_changed', '确认后通道配置变化，未改名')
            changes = self._changes(stores, origin, review['section'], old, new)
            if tuple(change.binding for change in changes) != review['binding']:
                raise CapabilityError('configuration_changed', '受影响的项目通道已变化，未改名')
            for change in changes:
                if resources.unknown_for(change.project_id):
                    raise CapabilityError('configuration_unknown', f'{change.name}有未核实任务，请先核实')
            self.guard(editor)
            resources.acquire(owner, origin, f'{editor.context.identity.name} · 网卡改名 {old} → {new}',
                              ('adapter:' + old, 'adapter:' + new, 'adapter:' + guid))
            # An interrupted dispatch must retain the original durable resource
            # fence. Only a definite rejection before/after readback can release it.
            uncertain = False
            confirmed = False
            try:
                self.guard(editor)
                emit(f'[网卡重命名] 操作员已确认：{old} → {new}；GUID={guid}')
                uncertain = True
                result = self.rename_service.rename(old, new, emit, expected_interface_guid=guid)
                uncertain = result.uncertain or result.ok
                if not result.ok:
                    return dict(message=result.message, state='unknown' if uncertain else 'failed')
                confirmed = True
                failed = []
                try:
                    self.publish(result.adapters, old, new, guid)
                except Exception as error:
                    failed.append('工作区网卡身份')
                    emit(f'[网卡重命名] 资源身份同步失败（{type(error).__name__}）')
                for change in changes:
                    try:
                        self.workspace.projects._validate_paths(self.workspace.projects.opened[change.project_id])
                        if self._digest(change.store.config_path) != change.digest:
                            raise RuntimeError('配置内容变化')
                        change.store.save([channel for channel in change.channels if channel.enabled], change.power)
                        if change.project_id == origin:
                            editor.cache = dict(channels=[asdict(c) for c in change.channels], power_serial_port=change.power,
                                device_ip=next((c.device_manage_ip for c in change.channels if c.device_manage_ip), ''))
                            editor.cache_hash = editor._file_hash()
                        emit(f'[网卡重命名] 已同步项目通道草稿：{change.name}')
                    except Exception as error:
                        failed.append(change.name)
                        emit(f'[网卡重命名] 项目通道草稿未完成同步：{change.name}（{type(error).__name__}）')
                if failed:
                    return dict(state='unknown', message='Windows 已确认改名，以下项目草稿未完成同步：' +
                        '、'.join(failed) + '。资源保护已保留，请核对系统和项目配置。')
                draft = editor._load()
                uncertain = False
                return dict(state='done', message=result.message, draft=draft, old=old, new=new, section=review['section'])
            except Exception as error:
                if not uncertain:
                    raise
                message = ('Windows 已确认改名，但配置或界面同步未完成' if confirmed else '未能确认网卡改名结果')
                emit(f'[网卡重命名] {message}（{type(error).__name__}），保留资源保护。')
                return dict(state='unknown', message=message + '。请核对系统和项目配置。')
            finally:
                resources.release(owner, uncertain=uncertain)
