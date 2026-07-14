import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from line_check_assistant.app import LineCheckAssistant
from line_check_assistant.config_store import ChannelConfig


class SampleParameterAppTests(unittest.TestCase):
    def test_parameter_targets_follow_enabled_channels_and_vlan_serial_mapping(self):
        fake_app = Mock()
        fake_app.channels = [
            ChannelConfig("channel_1", vlan_name="VLAN101", enabled=True),
            ChannelConfig("channel_2", vlan_name="VLAN102", enabled=False),
            ChannelConfig("channel_3", adapter_alias="VLAN103", enabled=True),
        ]

        result = LineCheckAssistant._parameter_channel_ports(fake_app)

        self.assertEqual(result, [("VLAN101", "COM1"), ("VLAN103", "COM3")])
        fake_app._capture_current_channel.assert_called_once_with()
