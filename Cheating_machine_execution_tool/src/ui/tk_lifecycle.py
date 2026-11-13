"""Explicit GUI-thread ownership for variables in disposable module windows."""
import threading


class TkScope:
    def __init__(self):
        self.owner = threading.main_thread().ident
        self.variables = []
        self.closed = False

    def check(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('Tk对象只能由GUI主线程访问和释放')

    def variable(self, factory, master, **kwargs):
        self.check()
        if self.closed:
            raise RuntimeError('Tk scope is closed')
        variable = factory(master=master, **kwargs)
        self.variables.append(variable)
        return variable

    def release(self):
        self.check()
        if self.closed:
            return
        self.closed = True
        # Removing a trace also deletes its Tcl command / bound Python closure.
        for variable in self.variables:
            for modes, identifier in variable.trace_info():
                variable.trace_remove(modes, identifier)
        self.variables.clear()
