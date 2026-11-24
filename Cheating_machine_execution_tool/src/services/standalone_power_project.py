"""Bind a standalone pipeline to one opened project and one saved revision."""
from dataclasses import asdict, dataclass
import configparser
import json
from pathlib import Path

from line_check_assistant.config_store import ChannelConfigStore
from src.models.project import PROJECT_FILE, ProjectContext, ProjectIdentity
from src.models.project_profile import dut_resource_keys
from src.services.project_power_plan import check_power_channel_binding
from src.services.project_profile_store import read_project_profile
from src.services.project_store import ProjectStore, configuration_digest


OPEN_GUIDANCE = '请从项目工作台打开所选项目，核对项目目录、通道和 DUT 档案，保存后关闭项目并重新打开独立挂测窗口。'
TOOL = 'Auto_power_on_off_tool'


def _digest(directory):
    if (not directory.is_dir() or directory.resolve() != directory or
            any(path.resolve() != path for path in directory.rglob('*'))):
        raise ValueError('项目配置目录缺失或含重定向路径')
    return configuration_digest(directory)


@dataclass(frozen=True)
class StandalonePowerProject:
    store: ProjectStore
    context: ProjectContext
    root: Path
    identity: ProjectIdentity
    digest: str

    @classmethod
    def open(cls, store, selected):
        if not selected:
            raise ValueError('请明确选择项目目录或项目清单')
        path = Path(selected).absolute()
        if path.resolve() != path or not (path.is_dir() or path.name == PROJECT_FILE):
            raise ValueError('请选择项目根目录或项目清单')
        root = path if path.is_dir() else path.parent
        manifest = root / PROJECT_FILE
        if manifest.resolve() != manifest:
            raise ValueError('项目清单路径已重定向')
        context = store.open(path)
        try:
            return cls(store, context, root, context.identity, _digest(context.saved_root / TOOL / 'config'))
        except BaseException:
            store.close(context)
            raise

    def _saved_profile(self, context):
        key = self.identity.project_id
        manifest = self.root / PROJECT_FILE
        if (context is not self.context or self.store.opened.get(key) is not context or
                key not in self.store.leases or context.root != self.root or context.identity != self.identity or
                manifest.resolve() != manifest or json.loads(manifest.read_text('utf-8')) != asdict(self.identity)):
            raise ValueError('所选项目、根目录或保存版本已改变')
        saved = context.saved_root / TOOL / 'config'
        if _digest(saved) != self.digest or _digest(context.config_dir) != self.digest:
            raise ValueError('项目配置未保存或已发生变化')
        profile = read_project_profile(saved)
        if not profile or profile['test_type'] != 'power_cycle' or not profile['duts']:
            raise ValueError('已保存版本缺少开关机项目 DUT 档案')
        schemes = configparser.RawConfigParser()
        schemes.read(saved / 'config.ini', encoding='utf-8')
        selected = schemes.get('ui_defaults', 'selected_profile', fallback='').strip().lower()
        name = schemes.get('config', selected, fallback='').strip()
        if (not name or Path(name).name != name or ':' in name or Path(name).suffix.lower() != '.ini' or
                not (saved / name).is_file()):
            raise ValueError('所选测试方案须使用本项目保存版本内的 INI 文件')
        return profile

    def validate_view(self, app):
        self._saved_profile(vars(app).get('project_context'))
        if (vars(app).get('_project_run_root', self.context.saved_root) != self.context.saved_root or
                app.store.config_path != self.context.config_dir / 'network_card_ip.ini'):
            raise ValueError('窗口加载的配置不属于所选项目')
        power_var = vars(app).get('power_serial_var')
        port = power_var.get() if power_var is not None else app.power_serial_port
        self._validate_channels(app.channels, port)

    def _validate_channels(self, channels, port):
        saved = ChannelConfigStore(self.context.saved_root / TOOL / 'config/network_card_ip.ini')
        selected = [row for row in channels if row.enabled]
        if (not selected or selected != [row for row in saved.load() if row.enabled] or
                str(port).strip().casefold() != saved.load_power_serial_port().casefold()):
            raise ValueError('所选通道或电源端口与已保存配置不一致')

    def prepare_run(self, app, ctx):
        self.validate_view(app)
        if ctx.legacy_tool_root != self.context.saved_root / TOOL:
            raise ValueError('挂测配置根目录与所选项目不一致')
        root = self.store.snapshot(self.context)
        run = StandalonePowerRun(self, root)
        ctx.legacy_tool_root = root / TOOL
        port = ChannelConfigStore(root / TOOL / 'config/network_card_ip.ini').load_power_serial_port()
        run.verify(ctx, port)
        ctx.standalone_power_run = run


@dataclass(frozen=True)
class StandalonePowerRun:
    project: StandalonePowerProject
    root: Path

    def resource_keys(self, ctx, bindings):
        profile = self.verify(ctx, ctx.app.power_serial_port)
        duts = profile['duts']
        by_channel = {dut['channel']: dut for dut in duts}
        identifiers = [dut['hardware_id'].casefold() for dut in duts]
        selected = []
        for channel, binding in zip(ctx.enabled_channels, bindings):
            dut = by_channel.get(binding.channel)
            if not dut or not dut['hardware_id'] or identifiers.count(dut['hardware_id'].casefold()) != 1:
                raise ValueError(f'CH{binding.channel:02d} 缺少唯一实物 ID，请核对项目 DUT 档案')
            check_power_channel_binding(dut, channel, resolved_alias=binding.alias)
            selected.append(dut)
        return dut_resource_keys(selected)

    def verify(self, ctx, port):
        binding = self.project
        profile = binding._saved_profile(binding.context)
        descriptor = self.root / 'run.json'
        if (self.root.parent != binding.root / 'runs' or self.root.resolve() != self.root or
                ctx.legacy_tool_root != self.root / TOOL or descriptor.resolve() != descriptor):
            raise ValueError('挂测运行目录与已绑定快照不一致')
        record = json.loads(descriptor.read_text('utf-8'))
        if (record.get('project_id') != binding.identity.project_id or record.get('run_id') != self.root.name or
                record.get('revision') != binding.identity.revision or
                _digest(ctx.legacy_tool_root / 'config') != binding.digest):
            raise ValueError('挂测运行快照与已保存的项目版本不一致')
        binding._validate_channels(ctx.channels, port)
        return profile
