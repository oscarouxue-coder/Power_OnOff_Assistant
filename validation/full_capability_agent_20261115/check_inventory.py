from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parents[2] / 'Cheating_machine_execution_tool'
sys.path.insert(0, str(root / 'scripts'))
import verify_baseline
result = verify_baseline.check_py_compile_inventory(root)
print(result.render())
sys.exit(not result.passed)
