"""Project wizard commands on the existing serialized workspace worker."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from line_check_assistant.config_store import ChannelConfig, ChannelConfigStore
from src.models.capabilities import CapabilityError, fingerprint
from src.services.project_model_presets import ProjectModelPresets

from src.services.project_profile_store import (
    PROFILE_FILE, configured_power_cycles, project_profile_digest, read_project_profile, write_project_profile,
)
from src.services.project_store import PROJECT_FILE, WizardCreateError, configuration_digest
from src.services.project_wizard_draft import ProjectWizardDraft
from src.services.qt_channel_configuration import channel_environment, prepare_channel_environment, profile_with_environment
from src.services.qt_configuration_service import QtConfigurationService


WIZARD_CREATION_COMMANDS = frozenset(('create_typed', 'wizard_create'))
WIZARD_COMMANDS = WIZARD_CREATION_COMMANDS | frozenset(('wizard_draft_get', 'wizard_draft_save',
    'wizard_profile_get', 'wizard_profile_save', 'wizard_preset_save'))


class QtProjectWizardService:
    def __init__(self, workspace, emit):
        self.workspace = workspace
        self.drafts = ProjectWizardDraft(workspace.directory)
        self.presets = ProjectModelPresets(workspace.directory)
        self.emit = emit

    def create(self, directory, name, profile, draft_token=None):
        return self._create(self.workspace.projects.create, directory, name, profile, draft_token)

    def create_in_parent(self, parent, name, profile, draft_token=None, environment=None):
        if environment is not None:
            source = self.workspace.projects.source_root
            try:
                environment = self._prepare_environment(profile, channel_environment(), environment, source)
            except (ValueError, CapabilityError) as error:
                raise WizardCreateError(f'环境配置校验失败：{error}。可从空白开始重新建项，或关闭以保留旧草稿') from error
        elif not any(dut.get('channel') is None for dut in profile.get('duts', ())):
            profile = dict(profile, environment_channels=True)
        return self._create(self.workspace.projects.create_in_parent, parent, name, profile, draft_token,
                            **({'environment': environment} if environment is not None else {}))

    def _create(self, create_project, directory, name, profile, draft_token, **options):
        if draft_token is not None:
            try:
                token = self.drafts.read()['token']
            except (OSError, ValueError, RecursionError) as error:
                raise WizardCreateError('创建前无法读取向导草稿，请核对工作区草稿文件后重新打开向导') from error
            if token != draft_token:
                raise WizardCreateError('创建前向导草稿已更新，请重新载入')
        context = create_project(directory, name, profile=profile, **options)
        if draft_token is not None:
            try:
                self.drafts.write(None, draft_token)
            except (OSError, ValueError, RuntimeError):
                self.emit('[项目向导] 项目已创建，工作区草稿保留，请核对')
        return context

    def profile(self, context):
        before = self._environment_revision(context)
        profile = read_project_profile(context.config_dir)
        environment = channel_environment(context.config_dir)
        cycles = self._cycles(context.config_dir)
        if self._environment_revision(context) != before:
            raise ValueError('读取时项目已变化，请重新打开向导核对')
        return self.with_presets({'profile': profile, 'token': project_profile_digest(profile),
                                  'saved_revision': context.identity.revision, 'environment': environment,
                                  'environment_revision': before, 'power_cycles': cycles})

    def draft(self):
        source = self.workspace.projects.source_root / 'Auto_power_on_off_tool/config'
        return self.with_presets(dict(self.drafts.read(), power_cycles=self._cycles(source)))

    @staticmethod
    def _cycles(directory):
        try:
            return configured_power_cycles(directory)
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _environment_revision(context):
        return fingerprint([context.identity.revision, (context.root / PROJECT_FILE).read_bytes().hex(),
                            configuration_digest(context.config_dir)])

    @staticmethod
    def _prepare_environment(profile, before, request, working_root):
        arguments = request['channels']
        aging = profile['test_type'] == 'service_aging'
        if aging:
            arguments = dict(arguments, power_serial_port='')
        after = prepare_channel_environment(before, arguments, working_root, preserve=True)
        if aging:
            after['power_serial_port'] = before['power_serial_port']
        return dict(after, assignments=request.get('assignments', {}))

    def with_presets(self, payload):
        try:
            presets = self.presets.list()
        except (OSError, ValueError, RecursionError) as exc:
            message = f'型号模板读取失败：{exc}'
            self.emit('[项目向导] ' + message, 'WARNING')
            return dict(payload, presets=[], preset_error=message)
        return dict(payload, presets=presets)

    def save_preset(self, context, revision, expected_version):
        if not revision or context.identity.revision != revision or self.workspace.projects.dirty(context):
            raise ValueError('源项目已更改，请先保存并重新核对版本')
        profile = read_project_profile(context.saved_root / 'Auto_power_on_off_tool/config')
        if not profile:
            raise ValueError('请先在项目向导保存型号和测试类型')
        if profile.get('environment_channels') and profile['test_type'] == 'power_cycle':
            profile = dict(profile, type_config={'target_cycles': self._cycles(context.saved_root / 'Auto_power_on_off_tool/config')})
        entries = self.presets.save(dict(profile, optional_steps=[]), expected_version)
        self.emit(f'[型号模板] 已从项目保存版本 {revision} 提取方案，模板版本 {expected_version + 1}')
        return {'presets': entries}

    def save_profile(self, context, profile, token, environment=None, final=False):
        if environment is not None:
            value = self._commit_profile(context, profile, token, environment, final)
            return {'profile': value, 'token': project_profile_digest(value),
                    'environment_revision': self._environment_revision(context)}
        if final:
            value = self._commit_profile(context, profile, token, None, True)
        else:
            value = write_project_profile(context.config_dir, profile, expected_profile_digest=token)
            self.emit('[项目向导] 项目设置草稿已保存')
        return {'profile': value, 'token': project_profile_digest(value)}

    def _commit_profile(self, context, profile, token, request, final):
        project_id = context.identity.project_id
        directory = context.config_dir
        self.workspace.guard_project_workers(context)
        owner = 'gui:qt-wizard:' + uuid4().hex
        self.workspace.resources.acquire(owner, project_id, context.identity.name, ('device-business', 'configuration'))
        uncertain = False
        try:
            self.workspace.projects._validate_paths(context)
            with ChannelConfigStore(directory / 'network_card_ip.ini').transaction():
                revision = self._environment_revision(context)
                if ((request is not None and revision != request['revision'])
                        or project_profile_digest(read_project_profile(directory)) != token):
                    raise ValueError('项目配置已变化，请重新打开向导核对')
                if request is not None:
                    before = channel_environment(directory)
                    after = self._prepare_environment(profile, before, request, context.working_root)
                    profile = profile_with_environment(profile, after, after['assignments'], before=before)
                profile_path = directory / PROFILE_FILE
                channel_path = directory / 'network_card_ip.ini'
                paths = [profile_path] if request is None else [channel_path, profile_path]
                with TemporaryDirectory(prefix='.qt-wizard-', dir=context.root) as temporary:
                    stage = Path(temporary)
                    if request is not None:
                        ChannelConfigStore(stage / channel_path.name).save(
                            [ChannelConfig(**row) for row in after['channels'] if row['enabled']], after['power_serial_port'])
                    value = write_project_profile(stage, profile)
                    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
                    written = {path: (stage / path.name).read_bytes() for path in paths}
                    if self._environment_revision(context) != revision:
                        raise ValueError('保存期间配置已变化，请重新打开向导核对')
                    changed = []
                    old_revision = context.identity.revision
                    try:
                        for path in paths:
                            if previous[path] != written[path]:
                                QtConfigurationService._replace(path, written[path])
                                changed.append(path)
                        if final:
                            self.workspace.projects.save(context)
                    except Exception:
                        uncertain = context.identity.revision != old_revision
                        for path in reversed(changed if not uncertain else ()):
                            try:
                                if path.read_bytes() != written[path]:
                                    raise RuntimeError('another writer changed configuration')
                                if previous[path] is None:
                                    path.unlink()
                                else:
                                    QtConfigurationService._replace(path, previous[path])
                            except Exception:
                                uncertain = True
                        files = '、'.join(path.name for path in paths)
                        raise ValueError(f'环境配置恢复未完成，请检查 {files} 和项目版本 {old_revision[:12]}' if uncertain else
                                         '环境配置保存失败，已恢复原草稿，请核对后重试') from None
            self.emit('[项目向导] 已保存项目设置' + ('并提交项目版本' if final else '到项目草稿'))
            return value
        finally:
            self.workspace.resources.release(owner, uncertain=uncertain)
