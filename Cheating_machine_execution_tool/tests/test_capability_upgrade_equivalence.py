"""Exercise actual GUI request collection against the Agent data builder; no worker runs."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig
from src.services.firmware_upgrade_service import build_upgrade_requests
from src.models.boot_entry import BOOT_ENTRY_OPTIONS


class UpgradeEquivalenceTests(unittest.TestCase):
    def test_four_modes_both_boot_methods_and_reset_options_match_gui_requests(self):
        with TemporaryDirectory() as temporary:
            firmware = Path(temporary).resolve() / 'tclinux_allinone'
            firmware.write_bytes(b'synthetic')
            channel = ChannelConfig('channel_1', vlan_name='VLAN116', adapter_alias='VLAN116', serial_port='COM16',
                network_card_ip='192.168.29.116', device_manage_ip='192.168.29.1', subnet_mask='255.255.255.128')
            snapshot = dict(channels=[asdict(channel)], upgrade_settings=dict(username=' user ', password=' secret '),
                power_serial_port='COM102', device_ip='192.168.29.2')
            for method in ('Tftp指令', 'Tftp Put', 'web打开网关', '页面升级'):
                for boot in BOOT_ENTRY_OPTIONS:
                    for reset in (False, True):
                        with self.subTest(method=method, boot=boot, reset=reset):
                            snapshot['channels'][0]['subnet_mask'] = '255.255.255.0'
                            channel.subnet_mask = '255.255.255.0'
                            variables = {name: Mock(get=Mock(return_value=value)) for name, value in dict(
                                upgrade_firmware_var=str(firmware), upgrade_username_var=' user ', upgrade_password_var=' secret ',
                                upgrade_restore_factory_var=reset, upgrade_transfer_var=method, upgrade_boot_entry_var=boot,
                                upgrade_parallel_count_var=2, device_ip_var=snapshot['device_ip']).items()}
                            context = SimpleNamespace(**variables, _log=Mock(), _set_upgrade_status=Mock(),
                                _selected_page_upgrade_channels=Mock(return_value=[channel]),
                                _selected_tftp_copy_upgrade_channels=Mock(return_value=[channel]),
                                _selected_power_serial_port=Mock(return_value='COM102'),
                                _full_package_tftp_server_ip_for_channel=LineCheckAssistant._full_package_tftp_server_ip_for_channel,
                                _page_upgrade_worker=Mock(), _parallel_tftp_command_upgrade_worker=Mock(),
                                _parallel_tftp_put_upgrade_worker=Mock(), _parallel_web_gateway_upgrade_worker=Mock())
                            args = dict(channel_ids=[1], firmware_path=str(firmware), restore_factory=reset,
                                        upgrade_type='页面升级' if method == '页面升级' else '全包升级')
                            if method != '页面升级':
                                args.update(transfer_method=method, boot_entry_method=boot)
                            with patch.object(LineCheckAssistant, '_launch_upgrade_run', return_value=True) as launch:
                                callback = LineCheckAssistant._start_page_upgrade if method == '页面升级' else LineCheckAssistant._start_full_package_upgrade
                                self.assertTrue(callback(context, skip_confirmation=True))
                            recorded = launch.call_args.args[2][0]
                            requests = recorded if method == '页面升级' else [item[1] for item in recorded]
                            self.assertEqual(requests, build_upgrade_requests(args, snapshot))
