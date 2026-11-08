import threading
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from src.core.zte_c300_onu import ZteC300OnuDriver
from src.core.zte_c600_onu import ZteC600OnuDriver
from src.core.zte_olt_telnet import OltCommandError, OltTelnetError, OperationCancelled
from src.core.zte_olt_registered_query import RegisteredOnuQuerySession
from src.models.onu_registration_models import OltConnection, RegisteredOnu
from src.services.onu_registration_service import OnuRegistrationService


CONNECTION = OltConnection("192.0.2.1", "192.0.2.2", "test", "test")


class TranscriptSession:
    """Require the exact read-only command sequence; unexpected commands fail."""

    def __init__(self, transcript):
        self.transcript = list(transcript)
        self.commands = []
        self.connected = False
        self.closed = False

    def __call__(self, connection, logger=None, cancel_event=None):
        self.logger = logger
        return self

    def __enter__(self):
        self.connected = True
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, command, **kwargs):
        self.commands.append(command)
        expected, response = self.transcript.pop(0)
        if command != expected:
            raise AssertionError(f"Expected {expected!r}, got {command!r}")
        if self.logger:
            self.logger(f"TX OLT {command}")
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        return response


def fixture(family):
    if family == "C300":
        pon = "gpon-olt_1/2/1"
        start = [
            ("terminal length 0", "ZXAN#"),
            ("show gpon onu state", "1/2/1:8 enable enable working 1(GPON)\n"
             "1/2/1:3 enable disable LOS 1(GPON)\n"
             "1/2/10:8 enable disable OffLine 1(GPON)\nZXAN#"),
        ]
        bulk = f"show gpon onu baseinfo {pon}"
        rows = {
            3: "gpon-onu_1/2/1:3 SD-41 sn SN:TEST0003 ready",
            8: "          gpon-onu_1/2/1:8 SD-41 sn SN:TEST0008 ready",
        }
        foreign = "gpon-onu_1/2/10:8 OTHER sn SN:WRONG ready"
        singles = {i: f"{bulk} {i}" for i in rows}
        prefix, state3 = "gpon-onu_1/2/1", "LOS"
    else:
        pon = "gpon_olt-1/1/5"
        start = [(f"show running-config-interface {pon}",
                  "onu 8 type TEST sn TEST0008\nonu 3 type TEST sn TEST0003\nZXAN#")]
        bulk = f"show gpon onu state {pon}"
        rows = {
            3: "1/1/5:3 enable disable OffLine N/A",
            8: "          1/1/5:8 enable enable working XGS-PON",
        }
        foreign = "1/1/50:8 enable disable LOS N/A"
        singles = {i: f"{bulk} {i}" for i in rows}
        prefix, state3 = "gpon_onu-1/1/5", "OffLine"
    expected = tuple(
        RegisteredOnu(family, pon, f"{prefix}:{i}", i,
                      "working" if i == 8 else state3, f"TEST{i:04d}",
                      "SD-41" if family == "C300" else "TEST")
        for i in (8, 3)
    )
    return pon, start, bulk, rows, foreign, singles, expected


class RegisteredQueryTests(unittest.TestCase):
    def run_query(self, family, transcript, event=None):
        fake = TranscriptSession(transcript)
        logs = []
        result = OnuRegistrationService(logger=logs.append, session_type=fake).query_registered_candidates(
            family, CONNECTION, fixture(family)[0], event
        )
        self.assertTrue(fake.closed)
        self.assertEqual(result.commands, tuple(fake.commands))
        return result, fake, logs

    def assert_bulk(self, family):
        pon, start, bulk, rows, foreign, singles, expected = fixture(family)
        output = "\x1b[0m" + rows[3] + "\r\n" + foreign + "\r\n" + rows[8] + "\r\nZXAN#"
        result, fake, logs = self.run_query(family, start + [(bulk, output)])
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.registered_onus, expected)
        self.assertFalse(fake.transcript)
        self.assertIn(output, result.output)
        self.assertTrue(any("候选 2 个" in line and "耗时" in line for line in logs))
        self.assertFalse(any("补查" in line for line in logs))

    def test_c300_bulk_identity_preserves_all_fields_and_order(self):
        self.assert_bulk("C300")

    def test_c600_bulk_state_preserves_all_fields_and_order(self):
        self.assert_bulk("C600")

    def assert_rejected(self, family):
        pon, start, bulk, rows, foreign, singles, expected = fixture(family)
        error = OltCommandError(bulk, "%Error Invalid input detected")
        script = start + [(bulk, error)] + [(singles[i], rows[i] + "\nZXAN#") for i in (8, 3)]
        result, fake, logs = self.run_query(family, script)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.registered_onus, expected)
        self.assertFalse(fake.transcript)
        self.assertIn(error.output, result.output)
        self.assertTrue(any("回退逐台" in line for line in logs))

    def test_c300_rejected_bulk_falls_back_to_original_queries(self):
        self.assert_rejected("C300")

    def test_c600_rejected_bulk_falls_back_to_original_queries(self):
        self.assert_rejected("C600")

    def assert_partial(self, family):
        pon, start, bulk, rows, foreign, singles, expected = fixture(family)
        script = start + [(bulk, rows[3] + "\n" + foreign + "\nZXAN#"),
                          (singles[8], rows[8] + "\nZXAN#")]
        result, fake, logs = self.run_query(family, script)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.registered_onus, expected)
        self.assertNotIn(singles[3], fake.commands)
        self.assertTrue(any("缺少 1 项" in line for line in logs))

    def test_c300_only_missing_identity_is_queried(self):
        self.assert_partial("C300")

    def test_c600_only_missing_state_is_queried(self):
        self.assert_partial("C600")

    def assert_empty(self, family):
        start = fixture(family)[1]
        start[-1] = (start[-1][0], "ONU Number: 0/0\nZXAN#")
        result, fake, logs = self.run_query(family, start)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.registered_onus, ())
        self.assertFalse(fake.transcript)

    def test_c300_empty_pon_skips_bulk_identity(self):
        self.assert_empty("C300")

    def test_c600_empty_config_skips_bulk_state(self):
        self.assert_empty("C600")

    def test_unparseable_bulk_supplements_all_without_losing_candidates(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                script = start + [(bulk, "unexpected table\nZXAN#")]
                script += [(singles[i], rows[i] + "\nZXAN#") for i in (8, 3)]
                result, fake, logs = self.run_query(family, script)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.registered_onus, expected)

    def test_missing_single_read_keeps_original_unknown_display(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                script = start + [(bulk, rows[3] + "\nZXAN#"),
                                  (singles[8], "%Error ONU data is null\nZXAN#")]
                result, fake, logs = self.run_query(family, script)
                self.assertTrue(result.ok, result.message)
                first = replace(expected[0], serial_number="", onu_type="") if family == "C300" else replace(
                    expected[0], state="未查询到状态"
                )
                self.assertEqual(result.registered_onus, (first, expected[1]))

    def test_single_supplement_never_uses_other_onu_identity_or_state(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                script = start + [(bulk, rows[3] + "\nZXAN#"),
                                  (singles[8], foreign + "\n" + rows[3] + "\nZXAN#")]
                result, fake, logs = self.run_query(family, script)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.registered_onus[0].serial_number, "" if family == "C300" else "TEST0008")
                self.assertEqual(result.registered_onus[0].state, "working" if family == "C300" else "未查询到状态")

    def test_disconnect_and_timeout_stop_without_fallback(self):
        for family in ("C300", "C600"):
            for reason in ("连接已关闭", "命令执行超时"):
                with self.subTest(family=family, reason=reason):
                    pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                    result, fake, logs = self.run_query(family, start + [(bulk, OltTelnetError(reason))])
                    self.assertFalse(result.ok)
                    self.assertIn(reason, result.message)
                    self.assertEqual(fake.commands[-1], bulk)
                    self.assertFalse(any("查询完成" in line for line in logs))

    def test_cancelled_bulk_does_not_fall_back(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                result, fake, logs = self.run_query(family, start + [(bulk, OperationCancelled("操作已停止"))])
                self.assertFalse(result.ok)
                self.assertEqual(result.registered_onus, ())
                self.assertEqual(fake.commands[-1], bulk)

    def test_cancel_event_set_during_bulk_response_prevents_result(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                event = threading.Event()

                def respond():
                    event.set()
                    return rows[3] + "\nZXAN#"

                result, fake, logs = self.run_query(family, start + [(bulk, respond)], event)
                self.assertFalse(result.ok)
                self.assertIn("停止", result.message)
                self.assertFalse(any("查询完成" in line for line in logs))

    def test_cancel_during_supplement_skips_remaining_onus(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                event = threading.Event()

                def respond():
                    event.set()
                    return rows[8] + "\nZXAN#"

                script = start + [(bulk, "ZXAN#"), (singles[8], respond)]
                result, fake, logs = self.run_query(family, script, event)
                self.assertFalse(result.ok)
                self.assertNotIn(singles[3], fake.commands)

    def test_pre_cancelled_query_never_connects(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                event = threading.Event()
                event.set()
                fake = TranscriptSession([])
                result = OnuRegistrationService(session_type=fake).query_registered_candidates(
                    family, CONNECTION, fixture(family)[0], event
                )
                self.assertFalse(result.ok)
                self.assertFalse(fake.connected)
                self.assertEqual(fake.commands, [])

    def test_duplicate_bulk_rows_are_supplemented(self):
        for family in ("C300", "C600"):
            with self.subTest(family=family):
                pon, start, bulk, rows, foreign, singles, expected = fixture(family)
                script = start + [(bulk, rows[3] + "\n" + rows[8] + "\n" + rows[8] + "\nZXAN#"),
                                  (singles[8], rows[8] + "\nZXAN#")]
                result, fake, logs = self.run_query(family, script)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.registered_onus, expected)
                self.assertNotIn(singles[3], fake.commands)


class RegisteredQueryDriverTests(unittest.TestCase):
    def test_c300_bulk_baseinfo_handles_ansi_indentation_and_other_pon(self):
        pon, start, bulk, rows, foreign, singles, expected = fixture("C300")
        driver = ZteC300OnuDriver()
        self.assertEqual(driver.build_registered_baseinfo_query_command(pon), bulk)
        result = driver.parse_registered_baseinfo(pon, "\x1b[0m" + rows[8] + "\r\n" + foreign)
        self.assertEqual(list(result), [expected[0].onu_interface])
        self.assertEqual(result[expected[0].onu_interface]["serial_number"], "TEST0008")

    def test_c600_bulk_state_keeps_all_phases_and_exact_pon(self):
        pon = "gpon_olt-1/1/5"
        driver = ZteC600OnuDriver()
        phases = ("working", "OffLine", "LOS", "DyingGasp", "syncMib", "AuthFail")
        output = "\r\n".join(
            f"          1/1/5:{i} enable disable {phase} N/A"
            for i, phase in enumerate(phases, 1)
        )
        output += "\n1/1/50:1 enable disable WRONG N/A\nZXAN#"
        self.assertEqual(driver.build_registered_state_query_command(pon), "show gpon onu state " + pon)
        self.assertEqual(driver.parse_registered_states(pon, output), dict(enumerate(phases, 1)))


class RegisteredQuerySessionTests(unittest.TestCase):
    def session(self, response_chunks, prompt=b"SITE-OLT#"):
        session = RegisteredOnuQuerySession(CONNECTION)
        session._tn = MagicMock()
        session._read_available = MagicMock(side_effect=[
            b"Username:", b"Password:", prompt,
        ] + response_chunks)
        session._login()
        return session

    def test_config_tags_and_other_promptlike_lines_do_not_finish_response(self):
        first = b"show running-config-interface gpon_olt-1/1/5\n!</if-intf>\nOTHER#\n"
        second = b"onu 8 type TEST sn TEST0008\n!</xpon>\nSITE-OLT#"
        session = self.session([first, second])
        output = session.execute("show running-config-interface gpon_olt-1/1/5")
        self.assertIn("onu 8 type TEST sn TEST0008", output)
        self.assertTrue(output.endswith("SITE-OLT#"))
        self.assertEqual(session._read_available.call_count, 5)

    def test_only_complete_learned_prompt_at_end_finishes_response(self):
        session = self.session([b"SITE-OLT# inside output\nSITE-", b"OLT#"], prompt=b"SITE-OLT#")
        output = session.execute("show gpon onu state")
        self.assertEqual(output, "SITE-OLT# inside output\nSITE-OLT#")

    def test_pagination_continues_across_config_tags(self):
        session = self.session([b"!</if-intf>\n--More--", b"onu 8 type TEST sn TEST0008\nSITE-OLT#"])
        output = session.execute("show running-config-interface gpon_olt-1/1/5")
        session._tn.write.assert_any_call(b" ")
        self.assertNotIn("--More--", output)
        self.assertIn("onu 8 type TEST sn TEST0008", output)

    def test_cli_rejection_is_reported_only_after_full_prompt(self):
        session = self.session([b"%Error Invalid input\nSITE-OLT#"])
        with self.assertRaises(OltCommandError) as caught:
            session.execute("show gpon onu state gpon_olt-1/1/5")
        self.assertIn("Invalid input", caught.exception.output)

    def test_cli_error_can_be_returned_for_original_single_read_fallback(self):
        session = self.session([b"%Error ONU data is null\nSITE-OLT#"])
        output = session.execute("show gpon onu state gpon_olt-1/1/5 8", fail_on_cli_error=False)
        self.assertIn("ONU data is null", output)

    def test_partial_config_without_prompt_times_out(self):
        session = self.session([b"!</if-intf>"])
        with patch("src.core.zte_olt_registered_query.time.monotonic", side_effect=[0.0, 0.0, 2.0]), \
             patch("src.core.zte_olt_registered_query.time.sleep"):
            with self.assertRaisesRegex(OltTelnetError, "命令执行超时"):
                session.execute("show running-config-interface gpon_olt-1/1/5", timeout=1)

    def test_cancelled_session_does_not_send_a_query(self):
        session = self.session([])
        session.cancel_event.set()
        with self.assertRaises(OperationCancelled):
            session.execute("show gpon onu state")
        self.assertEqual(session._tn, None)

    def test_default_query_service_receives_complete_config_before_parsing(self):
        from src.core.zte_olt_telnet import ZteOltTelnetSession
        pon, start, bulk, rows, foreign, singles, expected = fixture("C600")

        def connect(session):
            session._tn = MagicMock()
            session._read_available = MagicMock(side_effect=[
                b"Username:", b"Password:", b"SITE-OLT#",
                b"!</if-intf>\n",
                start[0][1].replace("ZXAN#", "SITE-OLT#").encode(),
                (rows[3] + "\n" + rows[8] + "\nSITE-OLT#").encode(),
            ])
            session._login()

        with patch.object(ZteOltTelnetSession, "connect", connect):
            result = OnuRegistrationService().query_registered_candidates("C600", CONNECTION, pon)
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.registered_onus, expected)
        self.assertEqual(result.commands, (start[0][0], bulk))


if __name__ == "__main__":
    unittest.main()
