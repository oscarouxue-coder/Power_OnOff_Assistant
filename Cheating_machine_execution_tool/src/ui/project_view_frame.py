"""Embeddable project view with explicit ownership of its application window.

The legacy standalone constructor remains supported. Embedded views never own the
shared root's close handler or destroy another project's widgets.
"""
from tkinter import Frame
from src.models.project_task import capture_ui_context
from src.services.project_runtime import current_run


class ProjectViewFrame(Frame):
    def attach_window(self, window, standalone):
        self._project_window = window
        self._standalone_window = standalone

    def title(self, value=None):
        if self._standalone_window or value is None:
            return self._project_window.title(value)

    def geometry(self, value=None):
        if self._standalone_window or value is None:
            return self._project_window.geometry(value)

    def minsize(self, *args):
        if self._standalone_window:
            return self._project_window.minsize(*args)

    def state(self, value=None):
        if self._standalone_window or value is None:
            return self._project_window.state(value)

    def protocol(self, *args):
        if self._standalone_window:
            return self._project_window.protocol(*args)

    def deiconify(self):
        return self._project_window.deiconify()

    def bind(self, sequence=None, func=None, add=None):
        if vars(self).get('_standalone_window'):
            return self._project_window.bind(sequence, func, add)
        return super().bind(sequence, func, add)

    def after(self, ms, func=None, *args):
        if func is None:
            return super().after(ms)
        pending = vars(self).setdefault('_project_after_ids', set())
        context = capture_ui_context()
        binding = current_run.get()
        project = vars(self).get('project_context')
        if binding and project is not None:
            record = binding[0].records.get(binding[1], {})
            if record.get('project_id') != project.identity.project_id:
                context.run(current_run.set, None)
        holder = []
        def invoke():
            if holder:
                pending.discard(holder[0])
            if not vars(self).get('_project_destroying'):
                context.run(func, *args)
        identifier = super().after(ms, invoke)
        holder.append(identifier)
        pending.add(identifier)
        return identifier

    def lift(self, *args):
        return self._project_window.lift(*args)

    def after_cancel(self, identifier):
        vars(self).get('_project_after_ids', set()).discard(identifier)
        return super().after_cancel(identifier)

    def destroy(self):
        if vars(self).get('_project_destroying'):
            return
        self._project_destroying = True
        for identifier in tuple(vars(self).get('_project_after_ids', ())):
            try:
                self.after_cancel(identifier)
            except Exception:
                pass
        callback = vars(self).get('_project_closed_callback')
        Frame.destroy(self)
        if callback:
            callback(self)
        if self._standalone_window:
            self._project_window.destroy()
