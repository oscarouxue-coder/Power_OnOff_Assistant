"""Run the shared read-only source checks into this stage's own evidence file."""
from verify_phase3 import main


if __name__ == '__main__':
    raise SystemExit(main('configuration_source_checks.json'))
