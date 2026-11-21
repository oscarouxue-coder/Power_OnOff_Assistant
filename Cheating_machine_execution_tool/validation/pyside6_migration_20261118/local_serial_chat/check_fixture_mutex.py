"""Check that separate simulated benches keep actual cross-process Windows mutex semantics."""
import json
from pathlib import Path
import subprocess
import sys
from unittest import TestCase
from uuid import uuid4

source = Path.cwd().resolve()
sys.path[:0] = [str(source), str(source / 'tests')]
from qt_execution_fakes import install_native_fixture_locks
from src.core.host_resource_lock import HostResourceLock

probe = """import sys
from src.core.host_resource_lock import HostResourceBusy, HostResourceLock
try:
    with HostResourceLock([sys.argv[1]], namespace=sys.argv[2], reentrant=False):
        print('acquired')
except HostResourceBusy:
    print('busy')
"""


def check():
    key = 'serial:synthetic-' + uuid4().hex
    case = TestCase()
    def state(namespace):
        return subprocess.check_output([sys.executable, '-c', probe, key, namespace], text=True).strip()

    host = HostResourceLock([key], reentrant=False)
    with host:
        rack = install_native_fixture_locks(case)
        try:
            with HostResourceLock([key], reentrant=False) as fixture:
                assert fixture.namespace == rack and rack != host.namespace
                assert state(rack) == state(host.namespace) == 'busy'
                assert state(rack + '-other') == 'acquired'
            assert state(rack) == 'acquired' and state(host.namespace) == 'busy'
        finally:
            case.doCleanups()
    assert state(host.namespace) == 'acquired'
    return dict(default_host_lock_held=True, same_simulated_bench_blocked_other_process=True,
                distinct_simulated_bench_independent=True, released_mutex_reacquired=True,
                physical_device_operations=0)


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
