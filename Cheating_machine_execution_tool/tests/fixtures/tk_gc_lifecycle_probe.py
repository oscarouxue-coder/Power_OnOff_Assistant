"""A retired test's Tcl interpreter must be reclaimed before later workers run."""
import gc
import threading
import tkinter as tk
import unittest
import weakref

from tk_test_windows import install_offscreen_windows


retired = []
finalized_on = []


class RetiredInterpreterTests(unittest.TestCase):
    def test_1_retire_mapped_root_with_python_cycle(self):
        install_offscreen_windows(self)
        self.root = tk.Tk()
        self.root.update_idletasks()
        self.root._probe_cycle = self.root
        retired.append(weakref.ref(self.root))
        weakref.finalize(self.root, lambda: finalized_on.append(threading.get_ident()))

    def test_2_previous_interpreter_is_gone_before_worker(self):
        # Do not force collection here: the runner must have done this between
        # tests, after unittest removed the preceding test case from its suite.
        self.assertIsNone(retired[0](), 'destroyed Tcl graph survived into the next test')
        self.assertEqual(finalized_on, [threading.main_thread().ident])
        worker = threading.Thread(target=gc.collect)
        worker.start()
        worker.join(3)
        self.assertFalse(worker.is_alive())
