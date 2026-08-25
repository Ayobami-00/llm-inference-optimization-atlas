from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(
        f"Implement the {args.profile} profile and write draft evidence beneath {args.work_dir}"
    )


if __name__ == "__main__":
    main()
