"""Project resource lease around the existing diagnostic transport lifecycle."""
import uuid

from src.core.ai_debug_transport import DiagnosticTransport


class ProjectDiagnosticTransport(DiagnosticTransport):
    def __init__(self, *args, resources, project_context, recovery_store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resources, self.project_context = resources, project_context
        self.recovery_store = recovery_store
        self.project_owner = 'gui:' + project_context.identity.project_id + ':debug-' + uuid.uuid4().hex
        self.project_acquired = False
        self.project_uncertain = False

    def open(self):
        if not self.project_acquired:
            alias = getattr(self.target, 'vlan', '')
            keys = ['adapter:' + alias] if alias else []
            self.resources.acquire(self.project_owner, self.project_context.identity.project_id,
                                   self.project_context.identity.name, keys)
            self.project_acquired = True
        try:
            return super().open()
        except BaseException:
            self.close()
            raise

    def _invalidate(self, reason, dispatched=False):
        self.project_uncertain |= bool(dispatched)
        return super()._invalidate(reason, dispatched)

    def close(self):
        try:
            super().close()
        except BaseException:
            self.project_uncertain = True
            raise
        finally:
            if self.project_acquired:
                self.project_acquired = False
                if self.recovery_store is not None:
                    try:
                        identity = tuple(getattr(self.target, key, None) for key in ('channel', 'host', 'port'))
                        self.project_uncertain |= any(
                            tuple(record.get(key) for key in ('channel', 'host', 'port')) == identity
                            for _, record in self.recovery_store.pending_recovery())
                    except Exception:
                        # Losing the recovery record is not proof of successful cleanup.
                        self.project_uncertain = True
                self.resources.release(self.project_owner, uncertain=self.project_uncertain)
