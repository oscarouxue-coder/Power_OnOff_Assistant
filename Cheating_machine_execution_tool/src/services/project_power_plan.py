"""Match a typed project's saved targets to the original power engine."""
from line_check_assistant.config_store import ChannelConfigStore
from line_check_assistant.network_ops import adapter_alias_from_display
from src.models.capabilities import CapabilityError
from src.models.project_review import ReviewRequired
from src.services.project_profile_store import active_project_duts, configured_power_cycles, project_profile_digest, read_project_profile
from src.services.project_store import configuration_digest


_UNBOUND = object()


def check_project_power_plan(context, channels, *, cycles=None, config_root=None, expected_profile=_UNBOUND,
                             enabled_only=False):
    if context is None:
        return
    saved = read_project_profile(context.saved_root / 'Auto_power_on_off_tool/config')
    if expected_profile is not _UNBOUND and saved != expected_profile:
        raise CapabilityError('configuration_changed', '已取得资源对应的项目档案发生变化，请重新确认')
    draft = read_project_profile(context.config_dir)
    if config_root is not None and read_project_profile(config_root / 'Auto_power_on_off_tool/config') != saved:
        raise CapabilityError('configuration_changed', '运行快照中的 DUT 档案与已核对版本不一致')
    if saved is None and draft is None:
        return
    if not saved or saved != draft:
        raise ReviewRequired('configuration_changed', '请先保存并核对当前项目档案', 'project', 'save')
    if saved['test_type'] != 'power_cycle':
        raise ReviewRequired('wrong_test_type', '全业务老化要求持续供电，请从业务老化工作台启动', 'project', 'start')
    targets = {}
    for channel in channels:
        prefix, _, suffix = channel.section.rpartition('_')
        if prefix != 'channel' or not suffix.isdecimal() or not 1 <= int(suffix) <= 16 or not channel.enabled:
            raise CapabilityError('target_changed', '原引擎通道编号无效或通道未启用')
        number = int(suffix)
        if number in targets:
            raise CapabilityError('target_changed', f'原引擎目标通道 CH{number:02d} 重复')
        targets[number] = channel
    directory = (config_root or context.saved_root) / 'Auto_power_on_off_tool/config'
    managed = saved.get('environment_channels')
    duts = active_project_duts(saved, directory)
    if enabled_only or managed:
        stored = ChannelConfigStore(directory / 'network_card_ip.ini').load()
        enabled = {c.section: c for c in stored if c.enabled}
        confirmed = {c.section: c for c in targets.values()}
        if confirmed != enabled:
            changed = sorted(key for key in enabled.keys() | confirmed.keys() if enabled.get(key) != confirmed.get(key))
            names = '、'.join('CH' + key.rsplit('_', 1)[-1].zfill(2) for key in changed)
            raise ReviewRequired('target_changed', f'{names} 的启用通道或资源配置与确认目标不一致，请重新确认',
                                 'channels', channels=(int(key.rsplit('_', 1)[-1]) for key in changed))
    if enabled_only:
        hardware_ids = [dut['hardware_id'].casefold() for dut in duts]
        duts = [dut for dut in duts if dut['channel'] in targets]
        missing = targets.keys() - {dut['channel'] for dut in duts}
        if missing:
            names = '、'.join(f'CH{number:02d}' for number in sorted(missing))
            raise ReviewRequired('target_changed', f'{names} 未映射到已保存的 DUT，请核对项目档案',
                                 'channels', 'dut', channels=sorted(missing))
        for dut in duts:
            hardware = dut['hardware_id'].casefold()
            if not managed and hardware and hardware_ids.count(hardware) != 1:
                raise ReviewRequired('target_changed', f"CH{dut['channel']:02d} 的实物标识在项目档案中重复，请核对",
                                     'channels', 'dut', channels=(dut['channel'],))
    if not targets or set(targets) != {dut['channel'] for dut in duts}:
        raise ReviewRequired('target_changed', '项目 DUT 映射与本次开关机目标通道不一致', 'channels', 'dut',
                             channels=sorted(set(targets) ^ {dut['channel'] for dut in duts}))
    for dut in duts:
        if not managed:
            if not dut['hardware_id']:
                raise ReviewRequired('target_changed', f"CH{dut['channel']:02d} 缺少 DUT 实物标识，请核对配置",
                                     'channels', 'dut', channels=(dut['channel'],))
            check_power_channel_binding(dut, targets[dut['channel']])
    try:
        target = configured_power_cycles(directory) if managed else saved['type_config'].get('target_cycles')
    except (KeyError, ValueError):
        raise ReviewRequired('configuration_incomplete', '请在测试项配置中设置有效的测试循环次数',
                             'configuration', 'number_of_tests') from None
    if target is None:
        raise ReviewRequired('configuration_incomplete', '请在项目档案填写目标开关机轮数', 'configuration', 'number_of_tests')
    if cycles is None:
        from src.services.legacy_power_test_service import LegacyPowerChannel, prepare_legacy_power_test_request
        root = config_root if config_root is not None else context.saved_root
        request = prepare_legacy_power_test_request(root / 'Auto_power_on_off_tool',
            [LegacyPowerChannel(number, channel.network_card_ip) for number, channel in targets.items()])
        cycles = request.number_of_tests
    if type(cycles) is not int or target != cycles:
        raise ReviewRequired('configuration_changed', f'计划 {target} 轮与执行配置 {cycles} 轮不一致，请核对后保存',
                             'configuration', 'number_of_tests')


def check_power_channel_binding(dut, channel, *, resolved_alias=''):
    number = dut['channel']
    expected_port = dut['serial_port']
    actual_port = channel.serial_port
    if expected_port and not actual_port:
        from src.core.serial_transport import vlan_to_serial_port
        try:
            actual_port = vlan_to_serial_port(adapter_alias_from_display(channel.vlan_name or channel.adapter_alias).lower())
        except ValueError as error:
            raise ReviewRequired('target_changed', f'CH{number:02d} 的串口映射无法核实',
                                 'channels', 'port', channels=(number,)) from error
    bindings = ((expected_port, actual_port), (dut['vlan'], channel.vlan_name or resolved_alias),
                (adapter_alias_from_display(dut['network_adapter']),
                 adapter_alias_from_display(channel.adapter_alias or channel.vlan_name or resolved_alias)))
    if any(expected and expected.casefold() != actual.strip().casefold() for expected, actual in bindings):
        raise ReviewRequired('target_changed', f'CH{number:02d} 的项目资源映射与执行配置不一致',
                             'channels', 'binding', channels=(number,))
    if dut['power_channel'] and dut['power_channel'].upper() not in (str(number), f'{number:02d}', f'CH{number:02d}'):
        raise ReviewRequired('target_changed', f'原引擎按 CH{number:02d} 控制供电，请核对电源通道',
                             'channels', 'power', channels=(number,))


def check_project_power_resume(project, projection, profile, channels, power_serial_port, *, config_root=None, local_confirmation=False):
    """A new job leases the selected targets while the old session performs the work."""
    if project is None:
        return
    original = getattr(projection, 'context', None)
    digest = getattr(original, 'power_profile_digest', '')
    saved = read_project_profile(project.saved_root / 'Auto_power_on_off_tool/config')
    if saved != profile:
        raise CapabilityError('configuration_changed', '续跑资源对应的项目档案发生变化，请重新确认')
    if profile is None and not digest:
        return
    if not profile or not digest or digest != project_profile_digest(profile):
        raise CapabilityError('configuration_changed', '续跑 DUT 档案与原批次不一致，未提交续跑')
    archive = getattr(original, 'configuration_root', None)
    if (original.project_id != project.identity.project_id or archive is None or
            archive.parent != project.root / 'runs' or archive.resolve() != archive or
            read_project_profile(archive / 'Auto_power_on_off_tool/config') != profile or
            configuration_digest(archive / 'Auto_power_on_off_tool/config') != original.power_config_digest):
        raise CapabilityError('configuration_changed', '原批次运行快照中的 DUT 档案无法核对')
    approved_root = config_root if config_root is not None else project.saved_root
    if configuration_digest(approved_root / 'Auto_power_on_off_tool/config') != original.power_config_digest:
        raise CapabilityError('configuration_changed', '当前执行配置与原批次快照不一致，未提交续跑')
    if (original.power_serial_port != power_serial_port or
            any(channel not in projection.channels for channel in channels)):
        raise CapabilityError('target_changed', '续跑目标通道或电源与原批次的资源绑定不符')
    # The session still uses its parent's full request, even when resuming one DUT.
    check_project_power_plan(project, projection.channels, expected_profile=profile,
                             config_root=config_root if config_root is not None else archive,
                             enabled_only=local_confirmation and getattr(original, 'power_enabled_only', False))
