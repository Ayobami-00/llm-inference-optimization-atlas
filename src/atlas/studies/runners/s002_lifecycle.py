from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import tarfile
from pathlib import Path

from atlas.studies.runners.common import artifact_path, cache_root

COMMIT = "aedb2a5e9ca3d4064148bbb919e0ddc0c1b70ab3"
SANDBOX_IMAGE = (
    "python:3.12.11-alpine3.22@"
    "sha256:efcdfa6a6b2fd2afb9c7dfa9a5b288a6f68338b5cfdebe6b637d986067d85757"
)


def build_root() -> Path:
    return cache_root() / "builds" / "llama.cpp" / COMMIT


def ensure_build() -> Path:
    target = build_root()
    server = target / "bin" / "llama-server"
    if server.is_file():
        return server
    temporary = target.with_name(f"{target.name}.building")
    if temporary.exists():
        shutil.rmtree(temporary)
    source_root = temporary / "source"
    source_root.mkdir(parents=True)
    with tarfile.open(artifact_path("llama-cpp-source.tar.gz"), "r:gz") as archive:
        archive.extractall(source_root, filter="data")
    source = next(path for path in source_root.iterdir() if path.is_dir())
    build = temporary / "build"
    configure = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build),
        "-DGGML_METAL=OFF",
        "-DGGML_ACCELERATE=ON",
        "-DLLAMA_CURL=OFF",
        "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_NUMBER=9637",
        f"-DLLAMA_BUILD_COMMIT={COMMIT}",
        "-DGIT_EXE=/usr/bin/false",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    subprocess.run(configure, check=True)
    subprocess.run(
        ["cmake", "--build", str(build), "--target", "llama-server", "-j", "4"],
        check=True,
    )
    (temporary / "bin").mkdir()
    for artifact in (build / "bin").iterdir():
        if artifact.is_file():
            shutil.copy2(artifact, temporary / "bin" / artifact.name)
    shutil.rmtree(source_root)
    shutil.rmtree(build)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary.replace(target)
    return server


def _image_available() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", SANDBOX_IMAGE],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def prepare() -> None:
    ensure_build()
    if not _image_available():
        subprocess.run(["docker", "pull", SANDBOX_IMAGE], check=True)


def start() -> None:
    server = build_root() / "bin" / "llama-server"
    if not server.is_file():
        raise RuntimeError("llama.cpp is not prepared; run atlas execution prepare")
    if not _image_available():
        raise RuntimeError("sandbox image is not prepared; run atlas execution prepare")


def destroy(work_dir: Path) -> None:
    pid_file = work_dir / "llama-server.pid"
    if not pid_file.is_file():
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, ValueError):
        pass
    pid_file.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "destroy"))
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "start":
        start()
    else:
        destroy(args.work_dir)


if __name__ == "__main__":
    main()
