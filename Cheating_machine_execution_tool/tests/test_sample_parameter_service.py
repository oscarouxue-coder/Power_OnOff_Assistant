import os
import re
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import STANDARD_PARAMETER_DEFINITIONS, SampleParameterRecord, SampleParameterWriteRequest
from src.services.sample_parameter_service import (
    preflight_parameter_targets,
    run_single_sample_parameter_write,
)


class FakeSession:
    def __init__(self, mismatch_variable=""):
        self.writes = []
        self.values = {}
        self.last_read = ""
        self.mismatch_variable = mismatch_variable

    def cursor(self):
        return len(self.writes)

    def write(self, data, sensitive=False):
        self.writes.append((data, sensitive))

    def send_line(self, text, sensitive=False):
        self.writes.append((text, sensitive))
        match = re.match(r'^ppctl set ([A-Z0-9_]+)="(.*)"$', text)
        if match:
            self.values[match.group(1)] = match.group(2)
        if text.startswith("ppctl get "):
            self.last_read = text.split()[-1]

    def wait_for_any(self, markers, _timeout, _cursor):
        markers = tuple(markers)
        if "#" in markers:
            return "#"
        return markers[0] if markers else None

    def peek_since(self, _cursor):
        value = self.values.get(self.last_read, "")
        if self.last_read == self.mismatch_variable:
            value = "wrong"
        return f"{self.last_read}={value}\n"


class FakeManager:
    def __init__(self, session):
        self.session = session
        self.acquired = []
        self.released = []

    def acquire_control(self, owner, settings, _path):
        self.acquired.append((owner, settings.port))
        return self.session

    def release(self, owner, port):
        self.released.append((owner, port))


def values():
    data = {definition.column: f"value-{index}" for index, definition in enumerate(STANDARD_PARAMETER_DEFINITIONS)}
    data["MAC"] = "02:00:00:00:00:01"
    data["Superuser Password"] = "secret-super"
    data["User Password"] = "secret-user"
    return data


class SampleParameterServiceTests(unittest.TestCase):
    def test_preflight_rejects_duplicate_and_incomplete_records(self):
        record = SampleParameterRecord("vlan101", values(), 2)
        bad_values = dict(values())
        bad_values["MAC"] = "not-a-mac"
        duplicate = SampleParameterRecord("VLAN101", bad_values, 3)
        result = preflight_parameter_targets([record, duplicate], [("vlan101", "COM1"), ("vlan102", "COM2")])

        self.assertFalse(result.ok)
        self.assertTrue(any("重复" in message for message in result.errors))
        self.assertTrue(any("vlan102" in message for message in result.errors))

    def test_write_reads_back_all_values_and_hides_sensitive_values(self):
        session = FakeSession()
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())
        messages = []

        result = run_single_sample_parameter_write(request, manager, messages.append, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.written_count, len(STANDARD_PARAMETER_DEFINITIONS))
        self.assertEqual(manager.released, [("sample-parameter:vlan101", "COM1")])
        self.assertTrue(any(text == "ppctl set FACTORY_MODE=0" for text, _ in session.writes))
        self.assertFalse(any("secret-super" in message or "secret-user" in message for message in messages))

    def test_failed_readback_retries_then_reports_failure_and_cleans_up(self):
        session = FakeSession(mismatch_variable="PRODUCT_CLASS")
        manager = FakeManager(session)
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())

        result = run_single_sample_parameter_write(request, manager, sleep_fn=lambda _seconds: None)

        self.assertFalse(result.ok)
        self.assertIn("产品名", result.failed_labels)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertEqual(sum(text.startswith('ppctl set PRODUCT_CLASS=') for text in writes), 3)
        self.assertIn("ppctl set FACTORY_MODE=0", writes)

    def test_cancel_before_start_does_not_enter_factory_mode(self):
        session = FakeSession()
        manager = FakeManager(session)
        cancel = threading.Event()
        cancel.set()
        request = SampleParameterWriteRequest("vlan101", "COM1", "root", "initial-secret", values())

        result = run_single_sample_parameter_write(request, manager, cancel_event=cancel, sleep_fn=lambda _seconds: None)

        self.assertTrue(result.cancelled)
        writes = [text for text, _ in session.writes if isinstance(text, str)]
        self.assertNotIn("ppctl set FACTORY_MODE=1", writes)
