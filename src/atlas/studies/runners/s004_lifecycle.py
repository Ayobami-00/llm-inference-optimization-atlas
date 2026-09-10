from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.studies.runners.s004_client import healthcheck
from atlas.utilities.serialization import load_data

BASE_URL = "http://127.0.0.1:30000"
MODEL_PATH = Path("/workspace/models/DeepSeek-V4.1-Flash-dba1be0")
MODEL_REPOSITORY = "deepseek-ai/DeepSeek-V4.1-Flash"
MODEL_REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
EXPECTED_RUNTIME_FILES: dict[str, tuple[str, int]] = {
    "sglang/srt/models/deepseek_v4.py": (
        "d69b85051bcf4535993d9c2a6625a1e86386e99e1954bb9c2c25e47cd577a8a9",
        205693,
    ),
    "sglang/srt/layers/engram.py": (
        "e8aba7161f19f0320944dda1aa3608d014620ea808045e810de89bc32d615626",
        38037,
    ),
    "sglang/srt/environ.py": (
        "27bfe2a3b90c76d8d233fc17d7c46906741c6102208fa3265f5a13b6faaac962",
        99410,
    ),
    "sglang/srt/configs/deepseek_v41.py": (
        "1035a371c565f5870d9390d9031606949d83b97eb2357279ddcb93b7e1ea76cd",
        4461,
    ),
}
EXPECTED_TREATMENT_SOURCE_FINGERPRINT = (
    "c292344963d409e4fb0a6c35de3ec94939121e43d5b99a78eb8e416d2c77fbd6"
)
EXPECTED_PACKAGE_MANIFEST_FINGERPRINT = (
    "6e7610e65ff433cfd252d5f44677dc4740779991ad050071e56c7420d752daca"
)
CONDITION_ENVIRONMENT = {
    "CFG021": {
        "SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE": "0",
        "SGLANG_ENABLE_DSV41_ENGRAM_KV_PREFETCH": "0",
    },
    "CFG022": {
        "SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE": "1",
        "SGLANG_ENABLE_DSV41_ENGRAM_KV_PREFETCH": "0",
    },
    "CFG023": {
        "SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE": "1",
        "SGLANG_ENABLE_DSV41_ENGRAM_KV_PREFETCH": "1",
    },
}
COMMON_ENVIRONMENT = {
    "SGLANG_DSV41_ENGRAM_HOST_TABLE_PIN": "1",
    "SGLANG_DSV41_ENGRAM_HOST_TABLE_LAYOUT": "shared",
    "SGLANG_ENABLE_DSV41_ENGRAM_DROP_PAGE_CACHE": "0",
}
EXPECTED_SERVER_CONFIGURATION: dict[str, Any] = {
    "tp_size": 4,
    "ep_size": 4,
    "pp_size": 1,
    "dp_size": 1,
    "mem_fraction_static": 0.8,
    "max_running_requests": 64,
    "schedule_policy": "fcfs",
    "num_continuous_decode_steps": 1,
    "context_length": 262400,
    "random_seed": 20260910,
    "fp8_gemm_runner_backend": "flashinfer_cutedsl",
    "json_model_override_args": '{"vision_config": null}',
    "enable_dp_attention": False,
    "speculative_algorithm": None,
    "enable_hierarchical_cache": False,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sglang_source_root() -> Path:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pathlib,sglang; print(pathlib.Path(sglang.__file__).parent)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(probe.stdout.strip())


def treatment_source_fingerprint(files: dict[str, dict[str, Any]]) -> str:
    rows = []
    for relative, record in files.items():
        size = record.get("actual_size_bytes")
        sha256 = record.get("actual_sha256")
        if isinstance(size, int) and isinstance(sha256, str):
            rows.append(f"{relative}\t{size}\t{sha256}\n")
    return hashlib.sha256("".join(sorted(rows)).encode()).hexdigest()


def runtime_fingerprint() -> dict[str, Any]:
    source_root = _sglang_source_root()
    files = {}
    errors = []
    for relative, (expected_sha, expected_size) in EXPECTED_RUNTIME_FILES.items():
        path = source_root.parent / relative
        actual_size = path.stat().st_size if path.is_file() else None
        actual_sha = sha256_file(path) if path.is_file() else None
        files[relative] = {
            "expected_size_bytes": expected_size,
            "actual_size_bytes": actual_size,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
        }
        if actual_size != expected_size or actual_sha != expected_sha:
            errors.append(
                f"Runtime fingerprint mismatch for {relative}: "
                f"size={actual_size} sha256={actual_sha}"
            )
    source_fingerprint = treatment_source_fingerprint(files)
    if source_fingerprint != EXPECTED_TREATMENT_SOURCE_FINGERPRINT:
        errors.append(f"Treatment source aggregate mismatch: {source_fingerprint}")
    package_environment = os.environ.copy()
    package_environment.pop("PYTHONPATH", None)
    packages = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        check=True,
        env=package_environment,
    ).stdout.splitlines()
    package_manifest = "\n".join(sorted(packages)) + "\n"
    package_manifest_sha256 = hashlib.sha256(package_manifest.encode()).hexdigest()
    if package_manifest_sha256 != EXPECTED_PACKAGE_MANIFEST_FINGERPRINT:
        errors.append(f"Package manifest mismatch: {package_manifest_sha256}")
    return {
        "sglang_source_root": str(source_root),
        "files": files,
        "treatment_source_fingerprint": source_fingerprint,
        "expected_treatment_source_fingerprint": EXPECTED_TREATMENT_SOURCE_FINGERPRINT,
        "package_manifest_sha256": package_manifest_sha256,
        "expected_package_manifest_sha256": EXPECTED_PACKAGE_MANIFEST_FINGERPRINT,
        "packages": sorted(packages),
        "valid": not errors,
        "errors": errors,
    }


def host_memory_snapshot(meminfo_path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    selected = {
        "MemTotal",
        "MemFree",
        "MemAvailable",
        "Buffers",
        "Cached",
        "SReclaimable",
        "Shmem",
        "Mlocked",
        "HugePages_Total",
        "HugePages_Free",
        "Hugepagesize",
    }
    values: dict[str, int] = {}
    for line in meminfo_path.read_text().splitlines():
        name, separator, payload = line.partition(":")
        if not separator or name not in selected:
            continue
        fields = payload.split()
        if not fields or not fields[0].isdigit():
            continue
        value = int(fields[0])
        if len(fields) > 1 and fields[1].casefold() == "kb":
            value *= 1024
        values[name] = value
    return values


def host_memory_policy_snapshot() -> dict[str, Any]:
    def read_setting(path: str) -> str | None:
        candidate = Path(path)
        return candidate.read_text().strip() if candidate.is_file() else None

    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    return {
        "transparent_hugepage_enabled": read_setting("/sys/kernel/mm/transparent_hugepage/enabled"),
        "transparent_hugepage_shmem_enabled": read_setting(
            "/sys/kernel/mm/transparent_hugepage/shmem_enabled"
        ),
        "memlock_soft_bytes": None if soft == resource.RLIM_INFINITY else soft,
        "memlock_hard_bytes": None if hard == resource.RLIM_INFINITY else hard,
        "settings_modified_by_runner": False,
    }


def hardware_snapshot() -> dict[str, Any]:
    query = (
        "index,name,memory.total,driver_version,temperature.gpu,power.draw,power.limit,"
        "clocks_throttle_reasons.active,ecc.errors.uncorrected.volatile.total"
    )
    result = subprocess.run(
        ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    gpus = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 9:
            raise RuntimeError(f"Unexpected nvidia-smi inventory row: {line}")
        gpus.append(
            {
                "index": int(fields[0]),
                "model": fields[1],
                "memory_mib": float(fields[2]),
                "driver": fields[3],
                "temperature_c": float(fields[4]),
                "power_w": float(fields[5]),
                "power_limit_w": float(fields[6]),
                "throttle_reasons": fields[7],
                "uncorrected_volatile_ecc": int(fields[8]),
            }
        )
    processes = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    valid = (
        len(gpus) == 4
        and all("B200" in str(gpu["model"]) for gpu in gpus)
        and all(gpu["driver"] == "595.91.07" for gpu in gpus)
        and not [line for line in processes if line.strip()]
        and all(gpu["uncorrected_volatile_ecc"] == 0 for gpu in gpus)
    )
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "host_memory": host_memory_snapshot(),
        "host_memory_policy": host_memory_policy_snapshot(),
        "gpus": gpus,
        "competing_compute_process_count": len([line for line in processes if line.strip()]),
        "valid": valid,
    }


def verify_model_manifest(repository_root: Path, model_path: Path = MODEL_PATH) -> dict[str, Any]:
    manifest_path = (
        repository_root / "studies/S004-deepseek-v41-engram-placement/v1/inputs/model-manifest.yaml"
    )
    manifest = load_data(manifest_path)
    if not isinstance(manifest, dict):
        raise RuntimeError("Invalid model manifest")
    records = []
    canonical_rows = []
    for item in manifest.get("files", []):
        canonical_rows.append(f"{item['path']}\t{int(item['size_bytes'])}\t{item['sha256']}\n")
        path = model_path / str(item["path"])
        actual_size = path.stat().st_size if path.is_file() else None
        actual_sha = sha256_file(path) if actual_size == int(item["size_bytes"]) else None
        records.append(
            {
                "path": item["path"],
                "expected_size": int(item["size_bytes"]),
                "actual_size": actual_size,
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_sha,
                "valid": actual_size == int(item["size_bytes"]) and actual_sha == item["sha256"],
            }
        )
    paths = [str(item["path"]) for item in manifest.get("files", [])]
    calculated_aggregate = hashlib.sha256("".join(sorted(canonical_rows)).encode()).hexdigest()
    calculated_total = sum(int(item["size_bytes"]) for item in manifest.get("files", []))
    metadata_valid = (
        len(paths) == len(set(paths))
        and len(paths) == int(manifest.get("file_count", -1))
        and calculated_total == int(manifest.get("total_size_bytes", -1))
        and calculated_aggregate == manifest.get("aggregate_sha256")
    )
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "aggregate_sha256": manifest.get("aggregate_sha256"),
        "calculated_aggregate_sha256": calculated_aggregate,
        "file_count": len(paths),
        "calculated_total_size_bytes": calculated_total,
        "metadata_valid": metadata_valid,
        "files": records,
        "valid": metadata_valid and bool(records) and all(item["valid"] for item in records),
    }


def prepare_model(repository_root: Path, model_path: Path = MODEL_PATH) -> dict[str, Any]:
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("huggingface_hub is required to prepare the S004 model") from error

    manifest_path = (
        repository_root / "studies/S004-deepseek-v41-engram-placement/v1/inputs/model-manifest.yaml"
    )
    manifest = load_data(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise RuntimeError("Invalid S004 model manifest")
    allow_patterns = [str(item["path"]) for item in manifest["files"]]
    model_path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPOSITORY,
        revision=MODEL_REVISION,
        local_dir=model_path,
        allow_patterns=allow_patterns,
        max_workers=4,
    )
    verification = verify_model_manifest(repository_root, model_path)
    if not verification["valid"]:
        raise RuntimeError("Downloaded model does not match the frozen S004 manifest")
    return verification


def preflight(
    repository_root: Path, output: Path, *, verify_weights: bool = True
) -> dict[str, Any]:
    if platform.system().lower() != "linux" or platform.machine().lower() != "x86_64":
        raise RuntimeError("The full S004 profile requires Linux x86_64")
    hardware = hardware_snapshot()
    runtime = runtime_fingerprint()
    model = (
        verify_model_manifest(repository_root)
        if verify_weights
        else {"valid": True, "skipped": True}
    )
    result = {"hardware": hardware, "runtime": runtime, "model": model}
    _write_json(output, result)
    if not hardware["valid"]:
        raise RuntimeError("Four idle NVIDIA B200 accelerators with clean ECC state are required")
    if not runtime["valid"]:
        raise RuntimeError("Pinned SGLang runtime fingerprint does not match RT004")
    if not model["valid"]:
        raise RuntimeError("Pinned model manifest is incomplete or mismatched")
    return result


def verify_preregistration_pushed(repository_root: Path) -> dict[str, Any]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    remote_refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)",
            "--contains",
            "HEAD",
            "refs/remotes/origin",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    study = load_data(repository_root / "studies/S004-deepseek-v41-engram-placement/v1/study.yaml")
    proposal = load_data(
        repository_root / "studies/S004-deepseek-v41-engram-placement/v1/proposal.yaml"
    )
    approved = (
        isinstance(proposal, dict) and proposal.get("approval", {}).get("state") == "approved"
    )
    result = {
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "remote_refs_containing_head": remote_refs,
        "worktree_clean": not status,
        "proposal_approved": approved,
        "study_id": study.get("id") if isinstance(study, dict) else None,
    }
    if status:
        raise RuntimeError("S004 requires a clean preregistration worktree before paid work")
    if not remote_refs:
        raise RuntimeError("S004 HEAD is not present on an origin remote ref")
    if not approved:
        raise RuntimeError("S004 public proposal approval is not recorded")
    if result["study_id"] != "S004":
        raise RuntimeError("S004 preregistration is missing")
    return result


def server_command(*, model_path: Path = MODEL_PATH, telemetry: bool = False) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "sglang.launch_server",
        "--model-path",
        str(model_path),
        "--trust-remote-code",
        "--tp-size",
        "4",
        "--ep-size",
        "4",
        "--pp-size",
        "1",
        "--dp-size",
        "1",
        "--mem-fraction-static",
        "0.80",
        "--max-running-requests",
        "64",
        "--schedule-policy",
        "fcfs",
        "--num-continuous-decode-steps",
        "1",
        "--context-length",
        "262400",
        "--cuda-graph-max-bs-decode",
        "64",
        "--random-seed",
        "20260910",
        "--fp8-gemm-backend",
        "flashinfer_cutedsl",
        "--json-model-override-args",
        '{"vision_config": null}',
        "--reasoning-parser",
        "deepseek-v41",
        "--tool-call-parser",
        "deepseekv41",
        "--host",
        "127.0.0.1",
        "--port",
        "30000",
    ]
    if telemetry:
        command.extend(["--enable-metrics", "--enable-request-time-stats-logging"])
    return command


def resolve_treatment(configuration: str, log_text: str) -> dict[str, Any]:
    host_status_lines = [
        line.casefold()
        for line in log_text.splitlines()
        if "engram host table" in line.casefold() and "layout=" in line.casefold()
    ]
    host_shared = bool(host_status_lines) and all(
        "layout=shared" in line for line in host_status_lines
    )
    host_pinned = host_shared and all(", pinned" in line for line in host_status_lines)
    prefetch = "Engram layer 14 KV prefetch enabled for BS=1 decode" in log_text
    expected = {
        "CFG021": (False, False, False, "device"),
        "CFG022": (True, True, False, "host-sync"),
        "CFG023": (True, True, True, "host-prefetch"),
    }[configuration]
    valid = (host_shared, host_pinned, prefetch) == expected[:3]
    return {
        "configuration": configuration,
        "host_table_status_line_count": len(host_status_lines),
        "host_shared_resolved": host_shared,
        "host_pinned_resolved": host_pinned,
        "prefetch_stream_resolved": prefetch,
        "requested_mode": expected[3],
        "resolved_mode": expected[3] if valid else "unexpected-fallback-or-unsupported",
        "valid": valid,
    }


def resolved_server_configuration(info: dict[str, Any]) -> dict[str, Any]:
    actual = {name: info.get(name) for name in EXPECTED_SERVER_CONFIGURATION}
    mismatches = {
        name: {"expected": expected, "actual": actual[name]}
        for name, expected in EXPECTED_SERVER_CONFIGURATION.items()
        if actual[name] != expected
    }
    return {
        "valid": not mismatches,
        "expected": EXPECTED_SERVER_CONFIGURATION,
        "actual": actual,
        "mismatches": mismatches,
    }


@dataclass
class ServerProcess:
    process: subprocess.Popen[bytes]
    log_path: Path
    pid_path: Path
    started_ns: int
    telemetry: bool

    def stop(self, timeout: float = 120) -> None:
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=30)
            except ProcessLookupError:
                pass
        self.pid_path.unlink(missing_ok=True)
        wait_for_gpu_release()


def wait_for_gpu_release(timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_processes: list[str] = []
    last_error = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            last_error = result.stderr.strip() or f"nvidia-smi exited {result.returncode}"
            time.sleep(1)
            continue
        last_processes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not last_processes:
            return
        time.sleep(1)
    raise RuntimeError(
        "GPU release could not be verified after server stop: "
        f"processes={last_processes} error={last_error or None}"
    )


def launch_server(
    *,
    configuration: str,
    work_dir: Path,
    telemetry: bool = False,
    readiness_timeout: float = 3600,
) -> tuple[ServerProcess, dict[str, Any], dict[str, Any], float]:
    if configuration not in CONDITION_ENVIRONMENT:
        raise ValueError(f"Unknown S004 configuration: {configuration}")
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = work_dir / "server.log"
    pid_path = work_dir / "server.pid"
    if pid_path.exists():
        raise RuntimeError(f"Server PID already exists: {pid_path}")
    environment = os.environ.copy()
    environment.update(COMMON_ENVIRONMENT)
    environment.update(CONDITION_ENVIRONMENT[configuration])
    started_ns = time.monotonic_ns()
    log_stream = log_path.open("wb")
    try:
        process = subprocess.Popen(
            server_command(telemetry=telemetry),
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
    finally:
        log_stream.close()
    server = ServerProcess(process, log_path, pid_path, started_ns, telemetry)
    pid_path.write_text(f"{process.pid}\n")
    deadline = time.monotonic() + readiness_timeout
    last_error = "server has not answered"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            server.stop()
            raise RuntimeError(f"SGLang exited with {process.returncode}; inspect {log_path}")
        try:
            info = healthcheck(BASE_URL, timeout=10)
            break
        except Exception as error:  # health errors are expected during weight load
            last_error = str(error)
            time.sleep(2)
    else:
        server.stop()
        raise RuntimeError(f"SGLang readiness timed out: {last_error}")
    readiness_ms = (time.monotonic_ns() - started_ns) / 1e6
    log_text = log_path.read_text(errors="replace")
    resolved_configuration = resolved_server_configuration(info)
    treatment = resolve_treatment(configuration, log_text)
    _write_json(work_dir / "resolved-server-configuration.json", resolved_configuration)
    _write_json(work_dir / "treatment-resolution.json", treatment)
    _write_json(work_dir / "server-info.json", info)
    if not resolved_configuration["valid"]:
        server.stop()
        raise RuntimeError(
            f"Resolved SGLang configuration does not match the frozen contract for "
            f"{configuration}; retained at {work_dir}"
        )
    if not treatment["valid"]:
        server.stop()
        raise RuntimeError(
            f"Requested Engram mode did not resolve for {configuration}; retained at {work_dir}"
        )
    return server, info, treatment, readiness_ms


def _kill_pid_file(pid_path: Path) -> None:
    if not pid_path.is_file():
        return
    try:
        pid = int(pid_path.read_text().strip())
        os.killpg(pid, signal.SIGTERM)
    except (ValueError, ProcessLookupError):
        pass
    pid_path.unlink(missing_ok=True)


def start_fake(work_dir: Path) -> None:
    pid_path = work_dir / "fake-server.pid"
    if pid_path.is_file():
        try:
            os.kill(int(pid_path.read_text().strip()), 0)
            return
        except (ValueError, ProcessLookupError):
            pid_path.unlink(missing_ok=True)
    log_path = work_dir / "fake-server.log"
    with log_path.open("wb") as log_stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "atlas.studies.runners.s004_fake_server"],
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path.write_text(f"{process.pid}\n")
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("S004 fake server exited during startup")
        try:
            healthcheck(BASE_URL, timeout=1)
            return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("S004 fake server did not become ready")


def destroy(work_dir: Path) -> None:
    _kill_pid_file(work_dir / "fake-server.pid")
    _kill_pid_file(work_dir / "server.pid")
    for pid_path in work_dir.rglob("server.pid"):
        _kill_pid_file(pid_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "healthcheck", "destroy"))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    args = parser.parse_args()
    repository_root = Path(os.environ["ATLAS_REPOSITORY_ROOT"])
    if args.action == "prepare" or args.profile == "full":
        gate = verify_preregistration_pushed(repository_root)
        _write_json(args.work_dir / "preregistration-gate.json", gate)
    if args.action == "prepare":
        preflight(
            repository_root,
            args.work_dir / "preflight-before-download.json",
            verify_weights=False,
        )
        verification = prepare_model(repository_root)
        _write_json(args.work_dir / "model-verification.json", verification)
    elif args.action == "start":
        if args.profile == "quick":
            start_fake(args.work_dir)
        else:
            preflight(repository_root, args.work_dir / "preflight.json", verify_weights=False)
    elif args.action == "healthcheck":
        healthcheck(BASE_URL)
    else:
        destroy(args.work_dir)


if __name__ == "__main__":
    main()
