"""Real dispatch/permission boundary with synthetic targets, no device operations."""
from dataclasses import asdict, replace
import gc
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_ai_conversation as fixture
from src.models.ai_permissions import FULL
from src.services.ai_serial_client import AiSerialClient
from src.services.pipeline_runtime import PipelineDispatcher


class MultichannelDispatchTests(unittest.TestCase):
    stop_services = fixture.ConversationTests.stop_services

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.targets = tuple(replace(next(iter(self.diag.targets.values())), channel=n,
            port="COM" + str(n), bind_ip="192.168.1." + str(20 + n)) for n in range(1, 9))
        self.diag.configure(self.profile, self.targets)
        self.parent = self.service.create_session(None, self.profile, scope="batch",
            batch_targets=[asdict(t) for t in self.targets], default_permission=FULL)

    def test_full_access_batch_does_not_block_ui_reader_while_waiting_for_dispatch(self):
        client = AiSerialClient(None)
        client.channel.dispatch_timeout = .3
        dispatcher = PipelineDispatcher(client.channel)
        reads = []
        def target_current(request):
            # The submitter is waiting for this dispatch. Probe that exact lock
            # boundary; timing the whole submission also includes SQLite fsync.
            available = self.service.lock.acquire(blocking=False)
            try:
                if available:
                    start = time.monotonic()
                    self.service.draft_message(self.id)
                    reads.append((True, time.monotonic() - start))
                else:
                    reads.append((False, 0))
            finally:
                if available:
                    self.service.lock.release()
            return True
        dispatcher.handlers["target_current"] = target_current
        self.service.target_current = client.target_current
        self.addCleanup(dispatcher.dispose)
        self.addCleanup(client.close)
        errors = []
        def submit():
            try:
                self.service.batch.submit(self.parent, "检查8台")
            except Exception as exc:
                errors.append(exc)
        with patch.object(self.service.batch, "run"):
            worker = threading.Thread(target=submit)
            worker.start()
            deadline = time.monotonic() + 3
            while worker.is_alive() and time.monotonic() < deadline:
                self.service.draft_message(self.id)
                dispatcher.poll(32)
                time.sleep(.002)
            if worker.is_alive():
                client.close()
            worker.join(2)
            self.service.jobs.join()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(reads, '必须实际执行GUI派发期间的读锁探测')
        self.assertTrue(all(available for available, duration in reads), '提交线程等待GUI时不得持有会话锁')
        self.assertLess(max(duration for available, duration in reads), .15)

    def test_dispatch_lock_probe_detects_a_submitter_holding_the_conversation_lock(self):
        client = AiSerialClient(None)
        dispatcher = PipelineDispatcher(client.channel)
        probes = []
        def handler(request):
            available = self.service.lock.acquire(blocking=False)
            probes.append(available)
            if available:
                self.service.lock.release()
            return True
        dispatcher.handlers['target_current'] = handler
        def submit():
            with self.service.lock:
                client.target_current(self.targets[0])
        worker = threading.Thread(target=submit)
        try:
            worker.start()
            deadline = time.monotonic() + 3
            while worker.is_alive() and time.monotonic() < deadline:
                dispatcher.poll(32)
                time.sleep(.002)
            worker.join(2)
        finally:
            client.close()
            dispatcher.dispose()
        self.assertFalse(worker.is_alive())
        self.assertEqual([False], probes, '负向对照必须识别持锁等待，不能把响应超时当作通过')

    def test_two_simultaneous_submissions_have_one_batch_and_one_user_message(self):
        barrier = threading.Barrier(2)
        release = threading.Event()
        outcomes = []
        def submit(text):
            try:
                self.service.batch.submit(self.parent, text)
                outcomes.append((text, True))
            except ValueError:
                outcomes.append((text, False))
        with patch.object(self.service.permissions, "activate", side_effect=lambda identifier: barrier.wait(2)), \
             patch.object(self.service.batch, "run", side_effect=lambda *args: release.wait(3)):
            workers = [threading.Thread(target=submit, args=(text,)) for text in ("first", "second")]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(2)
                self.assertTrue(all(not worker.is_alive() for worker in workers))
                self.assertEqual(sum(ok for _, ok in outcomes), 1)
                accepted = next(text for text, ok in outcomes if ok)
                self.assertEqual(self.store.chat(self.parent)["batch_request"]["text"], accepted)
                self.assertEqual([m["text"] for m in self.store.chat_items(self.parent) if m["role"] == "user"], [accepted])
            finally:
                release.set()
            self.service.jobs.join()

    def test_queue_full_preserves_previous_batch_and_status(self):
        previous = dict(text="previous")
        self.store.update_chat(self.parent, batch_request=previous)
        with patch.object(self.service.jobs, "full", return_value=True), self.assertRaisesRegex(ValueError, "队列已满"):
            self.service.batch.submit(self.parent, "new")
        self.assertEqual(self.store.chat(self.parent)["batch_request"], previous)
        self.assertNotIn(self.parent, self.service.running)
        self.assertFalse(any(m["role"] == "user" for m in self.store.chat_items(self.parent)))

    def test_admission_failure_restores_metadata(self):
        previous = dict(text="previous")
        self.store.update_chat(self.parent, batch_request=previous)
        status = self.store.chat(self.parent)["status"]
        with patch.object(self.service.jobs, "put_nowait", side_effect=queue.Full), self.assertRaises(queue.Full):
            self.service.batch.submit(self.parent, "new")
        self.assertEqual(self.store.chat(self.parent)["batch_request"], previous)
        self.assertEqual(self.store.chat(self.parent)["status"], status)
        self.assertNotIn(self.parent, self.service.running)
        self.assertFalse(any(m["role"] == "user" for m in self.store.chat_items(self.parent)))

    def test_failed_message_persistence_cannot_start_a_queued_ticket(self):
        with patch.object(self.service, "message", side_effect=OSError("synthetic store failure")), \
                patch.object(self.service.batch, "run") as run:
            with self.assertRaises(OSError):
                self.service.batch.submit(self.parent, "new")
            self.service.jobs.join()
        run.assert_not_called()
        self.assertIsNone(self.store.chat(self.parent).get("batch_request"))
        self.assertNotIn(self.parent, self.service.running)

    def test_target_change_during_permission_preflight_does_not_enqueue(self):
        def changed(identifier):
            self.diag.configure(self.profile, self.targets[:1])
        with patch.object(self.service.permissions, "activate", side_effect=changed), self.assertRaisesRegex(ValueError, "提交期间"):
            self.service.batch.submit(self.parent, "new")
        self.assertIsNone(self.store.chat(self.parent).get("batch_request"))
        self.assertNotIn(self.parent, self.service.running)

    def test_cancel_winning_during_preflight_does_not_enqueue(self):
        checks = iter((True, False))
        with self.assertRaisesRegex(InterruptedError, "未入队"):
            self.service.batch.submit(self.parent, "new", guard=lambda: next(checks))
        self.assertIsNone(self.store.chat(self.parent).get("batch_request"))
        self.assertNotIn(self.parent, self.service.running)

    def test_two_sessions_retain_their_own_batch_requests(self):
        second = self.service.create_session(None, self.profile, scope="batch",
            batch_targets=[asdict(t) for t in self.targets[:3]], default_permission=FULL)
        with patch.object(self.service.batch, "run"):
            self.service.batch.submit(self.parent, "eight")
            self.service.batch.submit(second, "three")
            self.service.jobs.join()
        self.assertEqual(self.store.chat(self.parent)["batch_request"]["channels"], list(range(1, 9)))
        self.assertEqual(self.store.chat(second)["batch_request"]["channels"], [1, 2, 3])

    def test_tk_heartbeat_survives_repeated_one_three_eight_channel_submissions(self):
        # Tk's interpreter and callback graph must never survive into a later
        # threaded test's GC. Keep this stress in its own UI-owner process.
        if os.environ.get("LINECHECK_MULTICHANNEL_TK_CHILD") != "1":
            env = dict(os.environ, LINECHECK_MULTICHANNEL_TK_CHILD="1", PYTHONIOENCODING="utf-8")
            env["PYTHONPATH"] = str(Path(__file__).parent) + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run([sys.executable, "-m", "unittest",
                "test_ai_multichannel_dispatch.MultichannelDispatchTests." + self._testMethodName],
                cwd=str(Path(__file__).resolve().parents[1]), env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        import tkinter as tk
        from tk_test_windows import install_offscreen_windows
        install_offscreen_windows(self)
        parents = [self.service.create_session(None, self.profile, scope="batch",
            batch_targets=[asdict(t) for t in self.targets[:count]], default_permission=mode)
            for count in (1, 3, 8) for mode in ("ask", "auto_review", FULL)]
        root = tk.Tk()
        root.withdraw()
        client = AiSerialClient(None)
        client.channel.dispatch_timeout = .5
        dispatcher = PipelineDispatcher(client.channel)
        dispatcher.handlers["target_current"] = lambda request: True
        self.service.target_current = client.target_current
        intervals, errors = [], []
        last = [time.monotonic()]
        after = [None]
        def tick():
            self.service.draft_message(self.id)
            dispatcher.poll(32)
            now = time.monotonic()
            intervals.append(now-last[0])
            last[0] = now
            after[0] = root.after(2, tick)
        def submit():
            try:
                for _ in range(5):
                    for identifier in parents:
                        self.service.batch.submit(identifier, "模拟批量检查")
                        self.service.jobs.join()
            except Exception as exc:
                errors.append(exc)
        with patch.object(self.service.batch, "run"):
            worker = threading.Thread(target=submit)
            worker.start()
            tick()
            try:
                deadline = time.monotonic()+10
                while worker.is_alive() and time.monotonic()<deadline:
                    root.update()
                    time.sleep(.001)
            finally:
                client.close()
                worker.join(2)
                if after[0]:
                    root.after_cancel(after[0])
                dispatcher.dispose()
                root.destroy()
                root = None
                tick = None
                gc.collect()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertGreater(len(intervals), 10)
        self.assertLess(max(intervals), .2)
        self.assertEqual(sum(m["role"] == "user" for identifier in parents for m in self.store.chat_items(identifier)), 45)


if __name__ == "__main__":
    unittest.main()
