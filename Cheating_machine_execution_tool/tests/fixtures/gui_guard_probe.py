"""Negative guard probes use dynamic lookup deliberately; never enter Tk native creation."""
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from unittest.mock import patch

from tk_test_windows import OffscreenTkWindows


def main():
    mode, marker = sys.argv[1:]
    if mode == 'managed':
        with OffscreenTkWindows() as windows:
            root = tk.Tk()
            root.update()
            windows.assert_offscreen()
        return
    if mode == 'tcl':
        interpreter = tk.Tcl()
        assert interpreter.eval('expr 6 * 7') == '42'
        return
    if mode == 'leak':
        OffscreenTkWindows().__enter__()
        return  # The guard must close and reject this leaked authorization.
    interpreter = tk.Tcl() if mode == 'loadtk' else None

    def native(*args, **kwargs):
        Path(marker).write_text('native constructor was entered', encoding='utf-8')
        raise RuntimeError('native constructor must not be called')

    def attempt():
        try:
            if mode == 'dialog':
                messagebox.showinfo('test', 'test')
            elif mode == 'loadtk':
                getattr(interpreter, 'load' + 'tk')()
            else:
                # The runtime layer must catch creation hidden from static AST
                # recognition, including a subclass calling the patched base.
                constructor = getattr(tk, 'T' + 'k')
                if mode == 'subclass':
                    class Indirect(constructor):
                        pass
                    constructor = Indirect
                constructor()
        except AssertionError:
            pass  # Deliberately swallow it: the child must still exit nonzero.
        else:
            raise AssertionError('missing strict guard')

    with patch('_tkinter.create', side_effect=native):
        if mode == 'thread':
            worker = threading.Thread(target=attempt)
            worker.start()
            worker.join(3)
            assert not worker.is_alive()
        else:
            attempt()
    assert not Path(marker).exists()


if __name__ == '__main__':
    main()
