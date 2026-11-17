"""Project history with user-scoped shared encrypted model accounts."""
from pathlib import Path

from src.services.ai_store import DiagnosticStore


class ProjectDiagnosticStore(DiagnosticStore):
    def __init__(self, directory, models, **kwargs):
        self.models = models
        super().__init__(directory, **kwargs)

    def profiles(self):
        return self.models.profiles()

    def save_profile(self, profile, key=None):
        return self.models.save_profile(profile, key)

    def delete_profile(self, identifier):
        return self.models.delete_profile(identifier)

    def key(self, profile):
        return self.models.key(profile)

    def model_context(self, profile):
        return self.models.model_context(profile)

    def cache_model_contexts(self, profile, models):
        return self.models.cache_model_contexts(profile, models)

    def import_profiles(self, legacy):
        """Preserve conflicting profile identities by assigning a new account ID.

        Re-encrypt through the existing cipher; an unreadable credential remains
        missing and requires local re-entry, never plaintext fallback.
        """
        from dataclasses import replace
        import uuid
        import json
        from src.services.ai_store import profile_fingerprint
        current = {p.id: p for p in self.models.profiles()}
        mapping = self.setting('workspace_model_mapping', {})
        selected = legacy.setting('selected_profile', '')
        for profile in legacy.profiles():
            original_id = profile.id
            migration_key = original_id + ':' + profile_fingerprint(profile)
            if migration_key in mapping and mapping[migration_key] in current:
                if selected == original_id:
                    self.set_setting('selected_profile', mapping[migration_key])
                continue
            if profile.id in current and current[profile.id] == profile:
                mapping[migration_key] = profile.id
                continue
            try:
                key = legacy.key(profile)
            except (RuntimeError, ValueError):
                key = None
            if profile.id in current:
                identifier = uuid.uuid5(uuid.NAMESPACE_URL, str(self.directory) + migration_key).hex
                profile = replace(profile, id=identifier, name=profile.name + "（导入）")
            saved = self.models.save_profile(profile, key)
            current[saved.id] = saved
            mapping[migration_key] = saved.id
            self.set_setting('workspace_model_mapping', mapping)
            if selected == original_id:
                self.set_setting('selected_profile', saved.id)
        with self.lock, self.db:
            # Project files carry history, not another copy of model credentials.
            self.db.execute('DELETE FROM profiles')
