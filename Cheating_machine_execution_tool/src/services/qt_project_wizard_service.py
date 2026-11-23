"""Project wizard commands on the existing serialized workspace worker."""
import getpass
from src.services.project_model_presets import ProjectModelPresets

from src.services.project_profile_store import project_profile_digest, read_project_profile, write_project_profile
from src.services.project_wizard_draft import ProjectWizardDraft


WIZARD_COMMANDS = frozenset(('create_typed', 'wizard_draft_get', 'wizard_draft_save',
    'wizard_profile_get', 'wizard_profile_save', 'wizard_preset_save', 'preparation_view', 'preparation_record'))


class QtProjectWizardService:
    def __init__(self, workspace, emit, emit_event=None):
        self.workspace = workspace
        self.drafts = ProjectWizardDraft(workspace.directory)
        self.presets = ProjectModelPresets(workspace.directory)
        self.preparations = {}
        self.emit = emit
        self.emit_event = emit_event

    def preparation(self, context):
        identifier = context.identity.project_id
        if identifier not in self.preparations:
            from src.services.project_preparation import preparation_for
            self.preparations[identifier] = preparation_for(context, emit=self.emit, emit_event=self.emit_event)
        return self.preparations[identifier]

    def create(self, directory, name, profile, draft_token=None):
        if draft_token is not None and self.drafts.read()['token'] != draft_token:
            raise ValueError('创建前向导草稿已更新，请重新载入')
        context = self.workspace.projects.create(directory, name, profile=profile)
        if draft_token is not None:
            try:
                self.drafts.write(None, draft_token)
            except (OSError, ValueError, RuntimeError):
                self.emit('[项目向导] 项目已创建，工作区草稿保留，请核对')
        return context

    def profile(self, context):
        profile = read_project_profile(context.config_dir)
        return self.with_presets({'profile': profile, 'token': project_profile_digest(profile),
                                  'saved_revision': context.identity.revision})

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
        entries = self.presets.save(profile, expected_version)
        self.emit(f'[型号模板] 已从项目保存版本 {revision} 提取方案，模板版本 {expected_version + 1}')
        return {'presets': entries}

    def save_profile(self, context, profile, token):
        value = write_project_profile(context.config_dir, profile, expected_profile_digest=token)
        return {'profile': value, 'token': project_profile_digest(value)}

    def record(self, context, params):
        steps = self.preparation(context)
        dut_id, step = params['dut_id'], params['step_id']
        action = params['action']
        operator = getpass.getuser()
        if action == 'begin':
            steps.begin(dut_id, step, params['token'], operator)
        elif action == 'manual':
            steps.record_manual(dut_id, step, params['token'], params['evidence'], operator)
        elif action == 'job':
            steps.link_job(dut_id, step, params['token'], params['job_id'], operator)
        elif action == 'finish':
            steps.finish(dut_id, step, params['attempt'], params['outcome'], params['evidence'], operator)
        elif action == 'verify':
            steps.verify(dut_id, step, params['token'], params['attempt'], params['passed'], params['evidence'], operator)
        elif action == 'skip':
            steps.skip(dut_id, step, params['token'], params['reason'], operator)
        else:
            raise ValueError('未知的准备步骤操作')
        return steps.snapshot()
