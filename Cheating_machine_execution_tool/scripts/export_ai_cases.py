"""Export the current user's confirmed cases without copying AI runtime databases."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.ai_case_store import export_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    export_snapshot(args.output)


if __name__ == "__main__":
    main()
