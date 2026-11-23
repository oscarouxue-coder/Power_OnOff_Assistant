"""Child process for exercising real host locks and simulating a lost process."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.capabilities import CapabilityError
from src.services.resource_lease_service import ResourceLeaseService
from src.services.workspace_resources import WorkspaceResources


if __name__ == '__main__':
    action, *arguments = sys.argv[1:]
    if action == 'crash':
        directory, key = arguments
        resources = WorkspaceResources(directory)
        resources.acquire('lost', 'A', 'A', [key])
        os._exit(0)
    if action != 'probe':
        raise ValueError(action)
    leases = ResourceLeaseService()
    for key in arguments:
        try:
            leases.acquire('child', [key])
        except CapabilityError as error:
            print(error.code)
        else:
            leases.release('child')
            print('acquired')
