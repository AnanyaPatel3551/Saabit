"""Report peak memory (RSS) of the Saabit server for startup, the sample, and a 25 MB upload.

Usage (from the repo root):
    backend\\.venv\\Scripts\\python.exe scripts\\memcheck.py

Each scenario runs in a fresh Python process that starts uvicorn in a thread, sends real
HTTP requests to itself, and prints its own peak RSS, so one scenario's peak never leaks
into another. The client side streams the upload from disk, so it adds only a few MB.
Exit code 1 if any scenario is over budget.
"""

import argparse
import gzip
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
SAMPLE = REPO / "data" / "sample" / "amazon_sale_report.csv.gz"
BUDGET_MB = 300
UPLOAD_LIMIT = 25 * 1024 * 1024
SCENARIOS = {
    "prepare_sample": "python -m app.prepare_sample (runs at image build)",
    "startup": "start the server and answer /api/health",
    "sample": "POST /api/datasets/sample (cache prepared)",
    "sample_cold": "POST /api/datasets/sample (no cache: builds it)",
    "upload_25mb": "POST /api/datasets with a 25 MB CSV",
}


def peak_rss_mb() -> float:
    """Peak resident memory of this process so far, in MB."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                )
            ]

        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD
        ]
        counters = Counters(cb=ctypes.sizeof(Counters))
        k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakWorkingSetSize / 2**20
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_scenario(name: str, upload: Path | None) -> dict:
    """Child process: do one scenario and return its peak RSS and HTTP results."""
    sys.path.insert(0, str(BACKEND))
    if name == "prepare_sample":
        from app.prepare_sample import main

        main()
        return {"peak_mb": peak_rss_mb(), "status": "ok"}

    import httpx
    import uvicorn
    from app.main import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    results = [f"health {httpx.get(f'{base}/api/health').status_code}"]
    if name.startswith("sample"):
        response = httpx.post(f"{base}/api/datasets/sample", timeout=120)
        results.append(f"sample {response.status_code}, rows {response.json().get('rows')}")
    if name == "upload_25mb" and upload is not None:
        with upload.open("rb") as f:
            response = httpx.post(
                f"{base}/api/datasets", files={"file": (upload.name, f)}, timeout=120
            )
        results.append(f"upload {response.status_code}, rows {response.json().get('rows')}")
    server.should_exit = True
    thread.join()
    return {"peak_mb": peak_rss_mb(), "status": "; ".join(results)}


def write_upload(dest: Path) -> Path:
    """A slice of the real sample, as close to 25 MB as whole rows allow, streamed from the .gz."""
    size = 0
    with gzip.open(SAMPLE, "rb") as src, dest.open("wb") as out:
        for line in src:
            if size + len(line) > UPLOAD_LIMIT:
                break
            out.write(line)
            size += len(line)
    return dest


def spawn(name: str, env: dict[str, str], upload: Path | None) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--scenario", name]
    if upload is not None:
        command += ["--upload", str(upload)]
    done = subprocess.run(
        command, cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if done.returncode != 0 or not lines:
        return {"peak_mb": float("nan"), "status": f"FAILED: {done.stderr.strip()[-300:]}"}
    return json.loads(lines[-1])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        upload = write_upload(tmp_path / "upload_25mb.csv")
        prepared, empty = tmp_path / "cache", tmp_path / "empty_cache"
        base_env = {**os.environ, "SAABIT_STORAGE_DIR": str(tmp_path / "storage")}
        caches = {"prepare_sample": prepared, "sample_cold": empty}
        print(f"25 MB upload file: {upload.stat().st_size:,} bytes; budget {BUDGET_MB} MB peak\n")
        print(f"{'scenario':<16}{'peak RSS':>10}  {'budget':<8}{'result'}")
        over = False
        for name, description in SCENARIOS.items():
            env = {**base_env, "SAABIT_SAMPLE_CACHE": str(caches.get(name, prepared))}
            result = spawn(name, env, upload if name == "upload_25mb" else None)
            ok = result["peak_mb"] < BUDGET_MB
            over |= not ok
            print(f"{name:<16}{result['peak_mb']:>7.0f} MB  {'OK' if ok else 'OVER':<8}"
                  f"{result['status']}   ({description})")
    return 1 if over else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=list(SCENARIOS))
    parser.add_argument("--upload", type=Path)
    args = parser.parse_args()
    if args.scenario:
        print(json.dumps(run_scenario(args.scenario, args.upload)))
        sys.exit(0)
    sys.exit(main())
