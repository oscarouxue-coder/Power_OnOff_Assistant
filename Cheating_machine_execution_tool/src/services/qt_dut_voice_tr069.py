"""Prepare Voice and TR069 editor requests for the existing DUT services."""
from dataclasses import asdict, dataclass, replace
from urllib.parse import urlsplit
from uuid import uuid4

from src.models.capabilities import CapabilityError
from src.models.dut_config_models import DutAdvancedConfigRequest, DutTr069Settings, DutVoiceSettings
from src.models.dut_voice_tr069_form import voice_choice_options
from src.services.dut_advanced_config_service import validate_dut_advanced_request
from src.services.dut_status_query_service import common_dut_status_settings


MODELS = {'voice': DutVoiceSettings, 'tr069': DutTr069Settings}
ACTION_LABELS = {
    'voice_query': '语音状态查询',
    'voice_configure': '语音配置',
    'tr069_query': 'TR069状态查询',
    'tr069_configure': 'TR069配置',
}
PRIVATE_FIELDS = {'voice': ('auth_password',), 'tr069': ('acs_password', 'connection_request_password')}


def redact_acs_url(url):
    """Keep user info out of summaries and results if the URL contains it."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return '（地址格式不正确）'
    if '@' not in parsed.netloc:
        return url
    return parsed._replace(netloc=parsed.netloc.rsplit('@', 1)[1]).geturl()


@dataclass(frozen=True)
class QueryIdentity:
    binding: tuple
    channels: tuple
    username: str
    password: str
    line_index: str


@dataclass(frozen=True)
class PrivateQuery:
    identifier: str
    identity: QueryIdentity
    settings: object
    all_succeeded: bool


class QtDutVoiceTr069:
    def __init__(self, owner):
        self.owner = owner
        self.queries = {}

    def _identity(self, binding, channels, requests, line_index):
        request = requests[0]
        return QueryIdentity(binding, tuple(channels), request.username, request.password, line_index)

    def _match(self, feature, identity):
        cached = self.queries.get(feature)
        return cached if cached is not None and cached.identity == identity else None

    def prepare(self, arguments, requests):
        feature, action = arguments['action'].rsplit('_', 1)
        line_index = arguments.get('line_index', '1') if feature == 'voice' else ''
        if feature == 'voice':
            try:
                if not 1 <= int(line_index) <= 8:
                    raise ValueError
            except (TypeError, ValueError):
                raise CapabilityError('invalid_parameters', '语音线路索引必须为1–8') from None
        options = dict(feature=feature, line_index=line_index, settings=None, advanced=(), source_query_id='')
        if action == 'query':
            return options

        raw = dict(arguments.get('settings', {}))
        if not raw or (feature == 'tr069' and 'manual_inform' not in raw):
            raise CapabilityError('invalid_parameters', '必须明确设备配置参数和本次动作选择')
        if feature == 'voice' and 'codecs' in raw:
            raw['codecs'] = tuple(raw['codecs'])
        try:
            settings = MODELS[feature](**raw)
        except TypeError:
            raise CapabilityError('invalid_parameters', '参数包含不属于此页的字段') from None
        if feature == 'voice' and settings.line_index != line_index:
            raise CapabilityError('target_changed', '语音线路索引与本次查询或配置不一致')

        identity = self._identity(self.owner.execution._binding(), arguments['channel_ids'], requests, line_index)
        cached = self._match(feature, identity)
        source_id = cached.identifier if cached else ''
        if arguments.get('query_id') and arguments['query_id'] != source_id:
            raise CapabilityError('query_expired', '查询的版本、目标或凭据已变化，请重新查询')
        observed = cached.settings if cached else None
        if feature == 'voice':
            choices = voice_choice_options(observed if observed is not None else DutVoiceSettings())
            settings = replace(settings, supported_dtmf_methods=choices['dtmf_method'],
                               supported_sip_modes=choices['sip_mode'], supported_codecs=choices['codecs'])
        elif observed is not None:
            settings = replace(settings, supported_fields=observed.supported_fields)
        advanced = tuple(DutAdvancedConfigRequest(**asdict(request), feature=feature, settings=settings)
                         for request in requests)
        errors = dict.fromkeys(error for request in advanced for error in validate_dut_advanced_request(request))
        if errors:
            message = '；'.join(errors)
            if feature == 'tr069' and settings.acs_url:
                message = message.replace(settings.acs_url, redact_acs_url(settings.acs_url))
            raise CapabilityError('invalid_parameters', message)
        return dict(options, settings=settings, advanced=advanced, source_query_id=source_id)

    def recheck(self, options, ids, requests):
        if options['settings'] is None:
            return
        identity = self._identity(self.owner.execution._binding(), ids, requests, options['line_index'])
        cached = self._match(options['feature'], identity)
        if (cached.identifier if cached else '') != options['source_query_id']:
            raise CapabilityError('query_expired', '确认期间查询能力已变化，请重新确认')

    def finish_query(self, options, values, ids, requests, binding):
        identity = self._identity(binding, ids, requests, options['line_index'])
        all_succeeded = len(values) == len(requests) and all(value.ok for value in values)
        observed = common_dut_status_settings(values) if all_succeeded else None
        with self.owner.lock:
            self.queries[options['feature']] = PrivateQuery(uuid4().hex, identity, observed, all_succeeded)

    def snapshot(self):
        with self.owner.lock:
            return {feature: dict(query_id=query.identifier, channel_ids=list(query.identity.channels),
                line_index=query.identity.line_index, all_succeeded=query.all_succeeded,
                settings=asdict(query.settings) if query.settings is not None else None)
                for feature, query in self.queries.items()}

    @staticmethod
    def public_settings(settings, feature):
        values = asdict(settings)
        for key in PRIVATE_FIELDS[feature]:
            values.pop(key, None)
        if feature == 'tr069':
            values['acs_url'] = redact_acs_url(values['acs_url'])
        return values

    @staticmethod
    def secrets(settings, feature):
        secrets = [getattr(settings, key) for key in PRIVATE_FIELDS[feature]]
        if feature == 'tr069':
            safe_url = redact_acs_url(settings.acs_url)
            if safe_url != settings.acs_url:
                secrets.append(settings.acs_url)
        return tuple(secret for secret in secrets if secret)

    def recorded(self, options):
        feature = options['feature']
        settings = options['settings']
        data = {'line_index': options['line_index']} if feature == 'voice' else {}
        if settings is not None:
            data['settings'] = {k:v for k,v in self.public_settings(settings, feature).items()
                                if not k.startswith('supported_')}
        return {feature: data}

    @staticmethod
    def summary(options):
        settings = options['settings']
        if options['feature'] == 'voice':
            text = '\n语音线路=' + options['line_index']
            if settings is not None:
                text += f'，SIP账号={"启用" if settings.account_enabled else "停用"}，模式={settings.sip_mode}，DTMF={settings.dtmf_method}'
            return text
        if settings is None:
            return ''
        action = '启用' if settings.manual_inform else '关闭'
        text = '\nACS=' + redact_acs_url(settings.acs_url)
        return text + f'\n配置后手动 Inform：{action}'
