"""WiFi GUI request projection; existing services retain all execution policy."""
from copy import deepcopy
from dataclasses import asdict, replace
import uuid

from src.models.capabilities import CapabilityError
from src.models.dut_config_models import DutWifiSettings, DutWifiRadioSettings, DutAdvancedConfigRequest
from src.models.dut_wifi_form import wifi_choice_options, wifi_editor_defaults
from src.services.dut_advanced_config_service import build_dut_wifi_settings_sequence, validate_dut_advanced_request
from src.services.dut_status_query_service import common_dut_status_settings


class QtDutWifi:
    FEATURES = ('wifi_2g', 'wifi_5g')
    ACTIONS = tuple(f + suffix for f in FEATURES for suffix in ('_query', '_configure'))

    def __init__(self, owner):
        self.owner = owner
        self.queries = {}

    def prepare(self, arguments, requests):
        action = arguments['action']
        feature = action.rsplit('_', 1)[0]
        ssid_index = arguments.get('ssid_index', '1')
        if ssid_index not in tuple(str(n) for n in range(1, 9)):
            raise CapabilityError('invalid_parameters', 'SSID索引必须为1–8')
        if action.endswith('_query'):
            return dict(settings=None, feature=feature, ssid_index=ssid_index, increment=False, advanced=())
        if 'settings' not in arguments or 'increment_ssid' not in arguments:
            raise CapabilityError('invalid_parameters', '必须明确WiFi参数和SSID递增选择')
        raw = deepcopy(arguments['settings'])
        try:
            if raw.get('peer_radio') is not None:
                raw['peer_radio'] = DutWifiRadioSettings(**raw['peer_radio'])
            settings = DutWifiSettings(**raw)
        except (TypeError, ValueError):
            raise CapabilityError('invalid_parameters', 'WiFi字段不完整或包含其它页面参数') from None
        expected = '2.4G' if feature == 'wifi_2g' else '5G'
        if settings.band != expected or settings.ssid_index != ssid_index:
            raise CapabilityError('target_changed', 'WiFi频段或SSID索引与当前页面不一致')
        # Only host-received status can supply supported lists. Client schema
        # excludes those fields, and these assignments also clear model defaults.
        cache = self.queries.get(feature)
        compatible = self._compatible(cache, arguments, requests, ssid_index)
        if arguments.get('query_id') and (not compatible or arguments['query_id'] != cache['query_id']):
            raise CapabilityError('query_expired', 'WiFi查询目标/凭据/索引/版本已变化，请重新查询')
        source = cache['settings'] if compatible and cache['settings'] is not None else wifi_editor_defaults(feature)
        # Tk recomputes on dual-band toggles only when the last query actually
        # supplied a peer Radio; do not invent a peer capability intersection.
        choices_source = replace(source, dual_band_enabled=settings.dual_band_enabled) if source.peer_radio is not None else source
        options = wifi_choice_options(choices_source)
        peer = settings.peer_radio
        if peer is not None:
            peer = replace(peer, supported_channels=options['peer_channel'],
                supported_bandwidths=options['peer_channel_bandwidth'], supported_modes=options['peer_operating_mode'],
                supported_transmit_powers=options['transmit_power'])
        settings = replace(settings, supported_channels=options['channel'], supported_bandwidths=options['channel_bandwidth'],
            supported_modes=options['operating_mode'], supported_security_modes=options['security_mode'],
            supported_transmit_powers=options['transmit_power'], peer_radio=peer if settings.dual_band_enabled else None)
        try:
            sequence = build_dut_wifi_settings_sequence(settings, len(requests), increment_enabled=arguments['increment_ssid'])
        except ValueError as error:
            raise CapabilityError('invalid_parameters', str(error)) from None
        advanced = tuple(DutAdvancedConfigRequest(**asdict(r), feature=feature, settings=s)
            for r, s in zip(requests, sequence))
        errors = [e for r in advanced for e in validate_dut_advanced_request(r)]
        if errors:
            raise CapabilityError('invalid_parameters', '；'.join(errors))
        return dict(settings=settings, feature=feature, ssid_index=ssid_index,
            increment=arguments['increment_ssid'], advanced=advanced,
            source_query_id=cache['query_id'] if compatible else '')

    def recheck(self, options, ids, requests):
        if options['settings'] is None:
            return
        cache = self.queries.get(options['feature'])
        arguments = dict(channel_ids=list(ids))
        compatible = self._compatible(cache, arguments, requests, options['ssid_index'])
        current_id = cache['query_id'] if compatible else ''
        if current_id != options['source_query_id']:
            raise CapabilityError('query_expired', '确认期间WiFi查询能力已变化，请重新确认')

    def _compatible(self, cache, arguments, requests, ssid_index):
        return bool(cache and cache['ids'] == tuple(arguments['channel_ids']) and
            cache['ssid_index'] == ssid_index and cache['binding'] == self.owner.execution._binding() and
            cache['credentials'] == (requests[0].username, requests[0].password))

    def finish_query(self, feature, values, ids, requests, binding, ssid_index):
        common = common_dut_status_settings(values)
        with self.owner.lock:
            self.queries[feature] = dict(query_id=uuid.uuid4().hex, ids=ids, binding=binding,
                credentials=(requests[0].username, requests[0].password), ssid_index=ssid_index, settings=common,
                all_succeeded=bool(values) and all(v.ok for v in values))

    def snapshot(self):
        with self.owner.lock:
            return {feature: dict(query_id=q['query_id'], channel_ids=list(q['ids']), ssid_index=q['ssid_index'],
                settings=asdict(q['settings']) if q['settings'] is not None else None, all_succeeded=q['all_succeeded'])
                for feature, q in self.queries.items()}

    @staticmethod
    def recorded(options):
        def public(value):
            if isinstance(value, dict):
                return {k:public(v) for k,v in value.items() if k!='password' and not k.startswith('supported_')}
            return value
        return dict(wifi=dict(feature=options['feature'], ssid_index=options['ssid_index'],
            increment_ssid=options['increment'], shared_settle=options['increment'] and len(options['advanced'])>1,
            targets=[dict(channel=r.channel, settings=public(asdict(r.settings))) for r in options['advanced']]))

    @staticmethod
    def summary(options):
        settings = options['settings']
        feature = options['feature']
        band = '2.4G' if feature == 'wifi_2g' else '5G'
        text = f'\n{band} WiFi，SSID索引={options["ssid_index"]}'
        if settings is not None:
            text += (f'，SSID={settings.ssid}，信道/带宽/协议={settings.channel}/{settings.channel_bandwidth}/{settings.operating_mode}'
                f'，公共发射功率={settings.transmit_power}%，双频合一={"是" if settings.dual_band_enabled else "否"}'
                f'，SSID递增={"是" if options["increment"] else "否"}')
            if settings.dual_band_enabled and settings.peer_radio:
                peer = settings.peer_radio
                text += f'\n另一Radio：{peer.band}，{peer.channel}/{peer.channel_bandwidth}/{peer.operating_mode}'
            if options['increment'] and len(options['advanced']) > 1:
                text += '\n按原流程全部下发后统一稳定等待60秒，再按原批量机制回读校验。'
            else:
                text += '\n按原单台配置/稳定等待60秒/回读流程执行。'
        return text
