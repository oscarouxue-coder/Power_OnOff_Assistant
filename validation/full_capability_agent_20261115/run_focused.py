"""Repeatable isolated checks; never connects to a DUT or a real model."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

root = Path(__file__).resolve().parents[2] / 'Cheating_machine_execution_tool'
os.chdir(str(root))
sys.path[:0] = [str(root), str(root / 'tests')]
temporary = str(Path(tempfile.gettempdir()).resolve())
os.environ.update({key: temporary for key in ('TEMP', 'TMP', 'TMPDIR')})
tempfile.tempdir = None
from tk_test_windows import OffscreenTkWindows

names = sys.argv[1:] or ['test_capabilities', 'test_capability_devices', 'test_capability_onu',
                        'test_ai_permissions', 'test_ai_actions', 'test_ai_monitor_permissions', 'test_ai_monitor_status']
with OffscreenTkWindows():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name) for name in names))
sys.exit(not result.wasSuccessful())
