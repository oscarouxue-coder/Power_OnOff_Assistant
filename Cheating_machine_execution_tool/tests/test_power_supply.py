import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.power_supply import ALL_CHANNELS_OFF_FRAME, ProgrammablePowerSupply, channel_power_frame
from src.services.power_on_service import power_on_selected_channels, turn_off_selected_channels, turn_on_selected_channels


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class PowerSupplyTests(unittest.TestCase):
    def test_channel_frames_match_legacy_power_supply_protocol(self):
        self.assertEqual(channel_power_frame(1, True), bytes((0x55, 0x01, 0xA0, 0x00, 0x01, 0xA0)))
        self.assertEqual(channel_power_frame(2, True), bytes((0x55, 0x01, 0xA0, 0x00, 0x02, 0xA3)))
        self.assertEqual(channel_power_frame(16, True), bytes((0x55, 0x01, 0xA0, 0x00, 0x10, 0xB1)))
        self.assertEqual(channel_power_frame(2, False), bytes((0x55, 0x01, 0xA1, 0x00, 0x02, 0xA2)))

    def test_controller_cycles_only_requested_channels_without_all_off_frame(self):
        fake_serial = FakeSerial()
        sleeps = []
        powered = []
        supply = ProgrammablePowerSupply(
            "com106",
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=sleeps.append,
        )

        with supply:
            result = supply.power_on_channels([2, 5], on_channel_powered=powered.append)

        self.assertEqual(result, [2, 5])
        self.assertEqual(
            fake_serial.writes,
            [
                channel_power_frame(2, False),
                channel_power_frame(2, True),
                channel_power_frame(5, False),
                channel_power_frame(5, True),
            ],
        )
        self.assertNotIn(ALL_CHANNELS_OFF_FRAME, fake_serial.writes)
        self.assertEqual(powered, [2, 5])
        self.assertEqual(sleeps, [1.5, 3, 1.5, 3])
        self.assertTrue(fake_serial.closed)

    def test_controller_turns_on_all_requested_channels_one_second_apart_without_powering_off(self):
        fake_serial = FakeSerial()
        sleeps = []
        powered = []
        supply = ProgrammablePowerSupply(
            "com106",
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=sleeps.append,
        )

        with supply:
            result = supply.turn_on_channels([2, 5], on_channel_powered=powered.append)

        self.assertEqual(result, [2, 5])
        self.assertEqual(fake_serial.writes, [channel_power_frame(2, True), channel_power_frame(5, True)])
        self.assertEqual(powered, [2, 5])
        self.assertEqual(sleeps, [1])
        self.assertTrue(fake_serial.closed)

    def test_controller_turns_off_only_requested_channels_one_second_apart_without_all_off_frame(self):
        fake_serial = FakeSerial()
        sleeps = []
        supply = ProgrammablePowerSupply(
            "com106",
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=sleeps.append,
        )

        with supply:
            result = supply.turn_off_channels([2, 5])

        self.assertEqual(result, [2, 5])
        self.assertEqual(fake_serial.writes, [channel_power_frame(2, False), channel_power_frame(5, False)])
        self.assertNotIn(ALL_CHANNELS_OFF_FRAME, fake_serial.writes)
        self.assertEqual(sleeps, [1])
        self.assertTrue(fake_serial.closed)

    def test_service_keeps_existing_total_power_on_wait_and_reports_real_power_frame(self):
        fake_serial = FakeSerial()
        clock = FakeClock()
        powered = []

        result = power_on_selected_channels(
            "COM106",
            [2],
            wait_seconds=10,
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            on_channel_powered=powered.append,
        )

        self.assertTrue(result.ok)
        self.assertEqual(powered, [2])
        self.assertEqual(clock.sleeps, [1.5, 3, 5.5])
        self.assertEqual(fake_serial.writes[-1], channel_power_frame(2, True))
        self.assertTrue(fake_serial.closed)

    def test_service_rejects_invalid_channel_without_opening_serial_port(self):
        opened = []
        result = power_on_selected_channels(
            "COM106",
            [17],
            serial_factory=lambda **_kwargs: opened.append(True),
        )

        self.assertFalse(result.ok)
        self.assertEqual(opened, [])

    def test_empty_power_serial_port_skips_power_operation_without_opening_port(self):
        opened = []
        messages = []

        result = power_on_selected_channels(
            "",
            [1],
            on_output=messages.append,
            serial_factory=lambda **_kwargs: opened.append(True),
        )

        self.assertTrue(result.ok)
        self.assertEqual(opened, [])
        self.assertIn("请手动重启样机后", result.message)
        self.assertEqual(messages, [result.message])

        result = turn_off_selected_channels("", [1], on_output=messages.append)

        self.assertTrue(result.ok)
        self.assertIn("请手动重启样机后", result.message)

    def test_turn_on_service_spaces_selected_channels_without_extra_startup_wait(self):
        fake_serial = FakeSerial()
        clock = FakeClock()

        result = turn_on_selected_channels(
            "COM106",
            [2, 5],
            wait_seconds=0,
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ok)
        self.assertEqual(fake_serial.writes, [channel_power_frame(2, True), channel_power_frame(5, True)])
        self.assertEqual(clock.sleeps, [1])
        self.assertTrue(fake_serial.closed)

    def test_turn_off_service_spaces_selected_channels_without_all_off_frame(self):
        fake_serial = FakeSerial()
        clock = FakeClock()

        result = turn_off_selected_channels(
            "COM106",
            [2, 5],
            serial_factory=lambda **_kwargs: fake_serial,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(result.ok)
        self.assertEqual(fake_serial.writes, [channel_power_frame(2, False), channel_power_frame(5, False)])
        self.assertNotIn(ALL_CHANNELS_OFF_FRAME, fake_serial.writes)
        self.assertEqual(clock.sleeps, [1])
        self.assertTrue(fake_serial.closed)


if __name__ == "__main__":
    unittest.main()
