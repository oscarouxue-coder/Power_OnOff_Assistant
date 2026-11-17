"""Explicit run identity propagation for existing workers and UI callbacks."""
from contextvars import ContextVar, copy_context
from functools import wraps

current_run = ContextVar('project_runtime_run', default=None)


def project_result_handoff(function):
    """A pending UI decision is part of the original operation, including modal loops."""
    @wraps(function)
    def invoke(*args, **kwargs):
        binding = current_run.get()
        if binding:
            binding[0].hold_handoff(binding[1], 1)
        try:
            return function(*args, **kwargs)
        finally:
            if binding:
                binding[0].hold_handoff(binding[1], -1)
    return invoke


def report_project_result(result=None, *, state=None):
    binding = current_run.get()
    if binding:
        service, owner = binding
        service.complete(owner, result, state)


def start_project_thread(thread):
    if current_run.get() and not getattr(thread, '_project_context_bound', False):
        context = copy_context()
        original = thread.run
        binding = current_run.get()
        def invoke():
            binding[0].update(binding[1], 'running')
            try:
                def run():
                    from src.models.project_task import project_task_scope
                    service, owner = binding
                    record = service.records[owner]
                    project = service.contexts[record['project_id']]
                    with project_task_scope(project.working_root, record['_path'].parent):
                        return original()
                return context.run(run)
            except BaseException:
                binding[0].complete(binding[1], state='unknown')
                raise
        thread.run = invoke
        thread._project_context_bound = True
    thread.start()
