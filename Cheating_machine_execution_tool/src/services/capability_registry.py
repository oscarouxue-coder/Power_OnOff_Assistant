"""Versioned explicit registry; no reflection or executable names from model input."""
from copy import deepcopy
import threading
from src.models.capabilities import CapabilityError, fingerprint, validate_schema


class CapabilityRegistry:
    def __init__(self):
        self._specs, self._cache = {}, {}
        self._lock = threading.RLock()
        self.revision = 0

    def register(self, spec):
        with self._lock:
            if spec.capability_id in self._specs or not callable(spec.handler):
                raise ValueError("能力重复或缺少受信任执行器")
            self._specs[spec.capability_id] = spec
            self.revision += 1
            self._cache.clear()

    def get(self, identifier):
        with self._lock:
            if identifier not in self._specs:
                raise CapabilityError("unsupported_capability", "能力尚未接入：" + str(identifier))
            return self._specs[identifier]

    def install_extension(self, spec):
        if not spec.capability_id.startswith("extension."):
            raise ValueError("扩展不能覆盖内置业务")
        with self._lock:
            self._specs[spec.capability_id] = spec
            self.revision += 1
            self._cache.clear()

    def describe(self, identifier):
        return deepcopy(self.get(identifier).public())

    def list(self, module="", query=""):
        with self._lock:
            return [dict(capability_id=s.capability_id, name=s.name, description=s.description,
                         status=s.status, risk=s.risk, execution_mode=s.execution_mode)
                    for s in self._specs.values() if
                    (not module or s.capability_id.split(".")[0] == module) and
                    (not query or query.casefold() in (s.name + s.description + s.capability_id).casefold())]

    def validate(self, identifier, arguments):
        spec = self.get(identifier)
        validate_schema(arguments, spec.input_schema)
        return spec

    def tool_schema(self, identifier, tool_name=None):
        spec = self.get(identifier)
        key = (identifier, spec.version, fingerprint(spec.input_schema), tool_name)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = dict(name=tool_name or identifier.replace(".", "_"),
                    description=spec.description, parameters=deepcopy(spec.input_schema))
            return deepcopy(self._cache[key])
