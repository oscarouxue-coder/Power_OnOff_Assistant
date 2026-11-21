"""Prepare a historical report session using the original conversation service."""
from collections import Counter
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.network_ops import adapter_alias_from_display
from line_check_assistant.test_item_config_store import TestItemConfigStore
from src.core.serial_transport import vlan_to_serial_port
from src.models.ai_diagnostics import DiagnosticTarget, ProviderProfile
from src.models.capabilities import fingerprint
from src.models.qt_ai_reports import ReportHandoffPreview
from src.services.ai_store import profile_fingerprint
from src.services.project_store import ProjectStore


@dataclass(frozen=True)
class _LegacyHandoff:
    token: str
    expires: float
    report_id: str
    revision: str
    target: DiagnosticTarget
    profile: ProviderProfile


class QtAiReportHandoff:
    def __init__(self, context, conversation):
        self.context = context
        self.conversation = conversation
        self.pending = None

    def configured_targets(self, number=None):
        ProjectStore._validate_paths(self.context)
        directory = self.context.config_dir
        channels_path, telnet_path = directory / 'network_card_ip.ini', directory / 'test_project_config.ini'
        if any(path.resolve() != path for path in (channels_path, telnet_path)):
            raise ValueError('项目配置文件指向重定向位置')
        rows = []
        for channel in ChannelConfigStore(channels_path).load():
            key = channel.section.partition('_')[2].lstrip('0')
            if channel.enabled and key.isascii() and key.isdecimal() and (number is None or str(number) == key):
                rows.append((int(key), channel))
        counts = Counter(key for key, _ in rows)
        unique = [(key, channel) for key, channel in rows if counts[key] == 1]
        if not unique:
            return ()
        telnet = TestItemConfigStore(telnet_path).load(required=True).telnet
        return tuple(self._configured_target(key, channel, telnet) for key, channel in unique)

    def _target(self, number):
        return next(iter(self.configured_targets(number)), None)

    @staticmethod
    def _configured_target(number, channel, telnet):
        vlan = adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).strip()
        port = channel.serial_port
        if not port and vlan:
            try:
                port = vlan_to_serial_port(vlan)
            except ValueError:
                port = ''
        return DiagnosticTarget(number, vlan, port, channel.network_card_ip.strip(), channel.device_manage_ip.strip(),
            int(telnet.port or 23), telnet.user, telnet.password, telnet.input_user_flag, telnet.input_password_flag,
            telnet.login_success_flag, bool(telnet.telnet_no_user_password_flag), subnet_mask=channel.subnet_mask)

    def prepare(self, report_id, revision, profile):
        self.pending = None
        report = self.conversation.store.report(report_id)
        if not revision or fingerprint(report) != revision:
            raise ValueError('报告已变化，请刷新报告后重试')
        if not profile or not profile.model.strip():
            raise ValueError('请先保存并选择模型配置')
        if report.get('target'):
            return self.conversation.create_session_from_report(report_id, profile, expected_report_sha256=revision)
        number = report.get('channel')
        target = self._target(number) if type(number) is int else None
        if target is None:
            self.conversation.emit(f'旧报告{report_id}没有可关联的同通道目标')
            raise ValueError('旧报告缺少目标快照，当前没有可关联的同通道目标')
        token = uuid4().hex
        self.pending = _LegacyHandoff(token, monotonic() + 120, report_id, revision, target, profile)
        self.conversation.emit(f'旧报告{report_id}等待本机确认关联通道{number}')
        target_label = f'通道 {number}  ·  {target.vlan or "无网卡"}  ·  {target.port or "无串口"}  ·  {target.host or "无管理地址"}'
        return ReportHandoffPreview(token, report_id, number, target_label)

    def finish(self, token, confirmed, profile):
        pending = self.pending
        if pending is None or pending.token != token:
            raise ValueError('关联确认已失效，请重新打开')
        self.pending = None
        if confirmed is False:
            self.conversation.emit(f'旧报告{pending.report_id}已取消关联')
            return None
        if confirmed is not True or monotonic() > pending.expires:
            raise ValueError('关联确认已过期，请重新打开')
        target = self._target(pending.target.channel)
        if target != pending.target:
            raise ValueError('当前目标已变化，未关联报告。请刷新后重新确认')
        if profile is None or profile_fingerprint(profile) != profile_fingerprint(pending.profile):
            raise ValueError('模型配置已变化，请重新确认')
        self.conversation.diagnostic.configure(profile, (target,))
        try:
            return self.conversation.create_session_from_report(pending.report_id, profile, target=target,
                legacy_confirmed=True, expected_report_sha256=pending.revision)
        finally:
            self.conversation.diagnostic.configure(profile, ())
