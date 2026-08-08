from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.wifi_interfaces import list_wifi_interface_names


class _FakeInterface:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class WifiInterfaceTests(unittest.TestCase):
    def test_names_are_trimmed_deduplicated_and_keep_discovery_order(self) -> None:
        interfaces = [
            _FakeInterface(" Wi-Fi 2 "),
            _FakeInterface("Wi-Fi"),
            _FakeInterface("Wi-Fi 2"),
            _FakeInterface(""),
        ]

        self.assertEqual(
            list_wifi_interface_names(lambda: interfaces),
            ["Wi-Fi 2", "Wi-Fi"],
        )


if __name__ == "__main__":
    unittest.main()
