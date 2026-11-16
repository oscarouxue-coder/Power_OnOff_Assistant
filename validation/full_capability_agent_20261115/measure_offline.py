"""Repeatable Fake benchmark. Does not call a real model, GUI app or hardware."""
from dataclasses import replace
import gc
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

source = Path(__file__).resolve().parents[2] / 'Cheating_machine_execution_tool'
os.chdir(str(source))
sys.path[:0] = [str(source), str(source / 'tests')]
temporary = str(Path(tempfile.gettempdir()).resolve())
os.environ.update({k: temporary for k in ('TEMP', 'TMP', 'TMPDIR')})
tempfile.tempdir = None
import psutil
from src.models.capabilities import CapabilityAuthority, CapabilityError
from src.services.capability_service import CapabilityService
from line_check_assistant.network_ops import CommandResult


def resources():
    process = psutil.Process()
    return dict(rss_bytes=process.memory_info().rss, threads=process.num_threads(),
                handles=process.num_handles() if hasattr(process, 'num_handles') else None)


def percentile(values, p):
    return sorted(values)[int((len(values) - 1) * p)]


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    image = root / 'tclinux_allinone'
    image.write_bytes(b'synthetic-firmware' * 1000)
    authority = CapabilityAuthority('offline', 'offline', 'operation', (1,), mode='full_access', grant_id='host-fake')
    snapshot = dict(channels=[dict(section='channel_1', vlan_name='vlan116', adapter_alias='vlan116', serial_port='COM16',
        network_card_ip='192.168.1.116', device_manage_ip='192.168.1.1', enabled=True)],
        power_serial_port='COM102', upgrade_settings={})
    class FakeManager:
        def diagnostic_state(self, port):
            return dict(control_owner='', closing_in_program=False)
    engine_count = [0]
    def engine(requests, manager, **kwargs):
        engine_count[0] += 1
        return [SimpleNamespace(request=r, result=CommandResult(True, 'fake done/write')) for r in requests]
    runtime = CapabilityService(root / 'runtime', FakeManager(), lambda: snapshot, upgrade_dispatch=engine)
    args = dict(channel_ids=[1], firmware_path=str(image), upgrade_type='全包升级', transfer_method='Tftp指令', boot_entry_method='账号密码登录')
    try:
        runtime.validate('firmware.upgrade', args, authority)
    except CapabilityError as exc:
        runtime.upgrades.confirm(authority.principal, exc.details['confirmation'].split()[-1])
    start = time.perf_counter()
    runtime.registry.tool_schema('firmware.upgrade')
    cold = (time.perf_counter() - start) * 1000
    timings = []
    for i in range(200):
        start = time.perf_counter()
        runtime.registry.tool_schema('firmware.upgrade')
        timings.append((time.perf_counter() - start) * 1000)
    gc.collect()
    before = resources()
    submits, totals, successes = [], [], 0
    for i in range(50):
        start = time.perf_counter()
        result = runtime.execute('firmware.upgrade', args, replace(authority, operation_id=str(i)))
        submits.append((time.perf_counter() - start) * 1000)
        deadline = time.monotonic() + 3
        while not runtime.jobs.idle and time.monotonic() < deadline:
            time.sleep(.001)
        if not runtime.jobs.idle:
            raise RuntimeError('fake job did not terminate')
        totals.append((time.perf_counter() - start) * 1000)
        successes += runtime.jobs.status(result['job_id'], authority)['state'] == 'succeeded'
    gc.collect()
    after = resources()
    stop = threading.Event()
    ticks = [0]
    running = threading.Event()
    def aging(context):
        running.set()
        while not stop.wait(.005):
            ticks[0] += 1
        return dict(ok=True)
    aging_job = runtime.jobs.start('fake.aging', dict(channel_ids=[1]), replace(authority, operation_id='aging'),
        ('device-business', 'channel:1'), aging)
    running.wait(1)
    # Model cancellation is a different token and never passed to the business job.
    model_stop = threading.Event()
    model_stop.set()
    baseline_start, baseline_ticks = time.perf_counter(), ticks[0]
    time.sleep(.5)
    baseline_seconds = time.perf_counter() - baseline_start
    baseline_progress = ticks[0] - baseline_ticks
    aging_resources_before = resources()
    load_start, load_ticks, iterations = time.perf_counter(), ticks[0], 0
    while time.perf_counter() - load_start < .5:
        runtime.registry.tool_schema('firmware.upgrade')
        runtime.files.list(root)
        runtime.metrics.record(dict(kind='offline_capability_load', iteration=iterations))
        iterations += 1
    load_seconds = time.perf_counter() - load_start
    load_progress = ticks[0] - load_ticks
    aging_resources_after = resources()
    continued = runtime.jobs.status(aging_job['job_id'], authority)['state'] == 'running'
    stop.set()
    while not runtime.jobs.idle:
        time.sleep(.001)
    runtime.jobs.close()
    gc.collect()
    closed = resources()
    result = dict(mode='offline Fake; no real model/DUT/network', iterations=50, real_model_latency=None,
        schema_cold_ms=cold, schema_cached_median_ms=statistics.median(timings), schema_cached_p95_ms=percentile(timings, .95),
        job_submit_median_ms=statistics.median(submits), job_total_median_ms=statistics.median(totals), job_total_p95_ms=percentile(totals, .95),
        fake_job_successes=successes, fake_job_success_rate=successes / 50, engine_calls=engine_count[0],
        schema_discovery_model_calls=0, resources_before=before, resources_after=after, resources_closed=closed,
        fake_aging_overlap=dict(progress_ticks=ticks[0], continued_after_model_stop=continued,
            baseline_ticks=baseline_progress, baseline_seconds=baseline_seconds,
            load_ticks=load_progress, load_seconds=load_seconds, load_iterations=iterations,
            baseline_ticks_per_second=baseline_progress / baseline_seconds, load_ticks_per_second=load_progress / load_seconds,
            resources_before=aging_resources_before, resources_after=aging_resources_after),
        limitations=['Fake image is small and engine has no flash duration', 'Real model/platform/long aging latency remains unmeasured'])

# Exercise the actual conversation queue, client protocol and hot tool bridge with Fake HTTP.
import test_capabilities as fixture
from test_ai_core import chat, call
scenario = fixture.CapabilityConversationTests('test_real_tool_loop_starts_job_without_discovery_or_review')
scenario.setUp()
try:
    scenario.confirm()
    scenario.send('帮我升级通道1', [chat(calls=[call('start_firmware_upgrade', scenario.args)]), chat('任务已启动')])
    while not scenario.runtime.jobs.idle:
        time.sleep(.001)
    records = [json.loads(line) for line in scenario.runtime.metrics.path.read_text(encoding='utf-8').splitlines()]
    result['fake_agent_scenario'] = dict(actual_model_requests=len(scenario.requests),
        turn=next(r for r in records if r['kind'] == 'agent_turn'), discovery_tool_calls=0)
    start_calls = len(scenario.requests)
    scenario.service.router._resolve('帮我升级通道1的固件', None, tuple(scenario.diag.targets.values()), scenario.profile, threading.Event(), False)
    result['explicit_channel_route_model_calls'] = len(scenario.requests) - start_calls
finally:
    scenario.doCleanups()
path = Path(__file__).with_name('offline_metrics.json')
path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
