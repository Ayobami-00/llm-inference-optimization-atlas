from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

IMAGE = "atlas-rag-cpu:v1"


def image_available() -> bool:
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False)
    return probe.returncode == 0


def prepare(bundle_dir: Path) -> None:
    if image_available():
        return
    subprocess.run(["docker", "build", "--pull", "--tag", IMAGE, str(bundle_dir)], check=True)


def start() -> None:
    if not image_available():
        raise RuntimeError("RAG image is not prepared; run atlas execution prepare")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "destroy"))
    parser.add_argument("--bundle-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.bundle_dir)
    elif args.action == "start":
        start()


if __name__ == "__main__":
    main()
