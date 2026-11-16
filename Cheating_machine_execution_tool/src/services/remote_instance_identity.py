"""Permanent per-installation slots outside the portable directory; fresh boot identities."""
import json
import os
from pathlib import Path
import uuid

from src.core.host_resource_lock import HostResourceLock, HostResourceBusy
from src.services.ai_project_store import project_directory


class RemoteInstanceIdentity:
    def __init__(self, app_dir, *, storage_root=None, slot=None):
        self.installation = os.path.normcase(str(Path(app_dir).resolve()))
        self.root = Path(storage_root) if storage_root else project_directory(app_dir) / "instances"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lease = None
        for number in ([slot] if slot is not None else range(1, 65)):
            if type(number) is not int or not 1 <= number <= 64:
                raise ValueError("实例槽位须为1至64")
            lease = HostResourceLock(["slot:" + str(self.root.resolve()) + ":" + str(number)])
            # Slots cannot nest even in one process; physical engine locks can.
            identity = (os.getpid(), lease.namespace, lease.keys[0])
            with HostResourceLock._guard:
                if identity in HostResourceLock._held:
                    if slot is not None:
                        raise HostResourceBusy("实例槽位已被占用")
                    continue
                try:
                    lease.acquire()
                except HostResourceBusy:
                    if slot is not None:
                        raise
                    continue
            self.lease, self.slot = lease, number
            break
        if self.lease is None:
            raise HostResourceBusy("没有可用实例槽位")
        try:
            self.directory = self.root / ("slot_" + str(self.slot))
            self.directory.mkdir(exist_ok=True)
            path = self.directory / "identity.json"
            if path.exists():
                value = json.loads(path.read_text(encoding="utf-8"))
                if value["installation"] != self.installation:
                    raise ValueError("实例身份不属于当前程序目录，请重新登记")
                self.instance_id = str(uuid.UUID(value["instance_id"]))
            else:
                self.instance_id = str(uuid.uuid4())
                temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
                temporary.write_text(json.dumps(dict(instance_id=self.instance_id,
                    installation=self.installation, slot=self.slot)), encoding="utf-8")
                os.replace(temporary, path)
            self.run_id = str(uuid.uuid4())
        except BaseException:
            self.close()
            raise

    def snapshot(self):
        return dict(instance_id=self.instance_id, run_id=self.run_id, slot=self.slot)

    def close(self):
        if self.lease:
            self.lease.close()
            self.lease = None
