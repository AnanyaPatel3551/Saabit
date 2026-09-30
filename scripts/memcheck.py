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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
SAMPLE = REPO / "data" / "sample" / "amazon_sale_report.csv.gz"
BUDGET_MB = 300
# Accepted exception: the image-build step may use more (see docs/LATER.md). It never runs
# on the Render instance, only on the build machine.
BUILD_BUDGET_MB = 350
UPLOAD_LIMIT = 25 * 1024 * 1024
SCENARIOS = {
    "prepare_sample": "python -m app.prepare_sample (image build only)",
    "startup": "start the server and answer /api/health",
    "sample": "POST /api/datasets/sample (cache prepared)",
    "upload_25mb": "POST /api/datasets with a 25 MB CSV",
    "confirm_25mb": "upload a 25 MB CSV, then POST /confirm (cleaning)",
    "run_10_plans": "10 plans through both engines on the full sample",
    "plan_10_questions": "10 questions through the planner (local stub instead of Groq)",
}
STUB_KEY = "memcheck-stub-not-a-real-key"
PLANS = [
    {"metric": "revenue", "group_by": ["month"]},
    {"metric": "orders", "group_by": ["week"]},
    {"metric": "cancellation_rate", "group_by": ["fulfilment"]},
    {"metric": "cancellation_rate", "group_by": ["state"], "sort": {"by": "value", "dir": "desc"}},
    {"metric": "aov", "group_by": ["sku"]},
    {"metric": "units", "group_by": ["category", "fulfilment"]},
    {"metric": "revenue", "date_range": {"start": "2022-05-01", "end": "2022-05-31"}},
    {"metric": "orders", "filters": [{"column": "state", "values": ["rajasthan"]}]},
    {"metric": "revenue", "group_by": ["city"], "sort": {"by": "value", "dir": "desc"},
     "limit": 10},
    {"metric": "cancellation_rate", "group_by": ["month", "fulfilment"],
     "filters": [{"column": "category", "op": "in", "values": ["Set", "kurta"]}]},
]


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
    if name == "run_10_plans":
        sample_id = httpx.post(f"{base}/api/datasets/sample", timeout=120).json()["dataset_id"]
        verified, slowest = 0, 0.0
        for plan in PLANS:
            started = time.perf_counter()
            response = httpx.post(f"{base}/api/datasets/{sample_id}/run", json=plan, timeout=120)
            slowest = max(slowest, time.perf_counter() - started)
            verified += response.status_code == 200 and response.json()["verified"]
        results.append(f"{verified}/{len(PLANS)} verified, slowest {slowest:.2f}s")
    if name == "plan_10_questions":
        sample_id = httpx.post(f"{base}/api/datasets/sample", timeout=120).json()["dataset_id"]
        planned = 0
        for number in range(len(PLANS)):
            response = httpx.post(f"{base}/api/datasets/{sample_id}/plan",
                                  json={"question": f"memcheck question {number}"}, timeout=120)
            planned += response.status_code == 200 and response.json()["plan"]["status"] == "ok"
        results.append(f"{planned}/{len(PLANS)} planned")
    if name in ("upload_25mb", "confirm_25mb") and upload is not None:
        with upload.open("rb") as f:
            response = httpx.post(
                f"{base}/api/datasets", files={"file": (upload.name, f)}, timeout=120
            )
        body = response.json()
        results.append(f"upload {response.status_code}, rows {body.get('rows')}")
        if name == "confirm_25mb":
            roles = {r["role"]: r["column"] for r in body["roles"]}
            response = httpx.post(
                f"{base}/api/datasets/{body['dataset_id']}/confirm",
                json={"roles": roles}, timeout=120,
            )
            results.append(f"confirm {response.status_code}, clean rows "
                           f"{response.json().get('rows_out')}")
    server.should_exit = True
    thread.join()
    return {"peak_mb": peak_rss_mb(), "status": "; ".join(results)}


def start_llm_stub() -> str:
    """A local stand-in for Groq's chat completions endpoint that returns the PLANS in turn.

    It lets the planner path be measured with no network and no real key.
    """
    replies = iter(PLANS * 100)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            content = json.dumps({"status": "ok", **next(replies)})
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/v1"


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
        # prepare_sample runs first and writes the cache every later scenario reads.
        env = {
            **os.environ,
            "SAABIT_STORAGE_DIR": str(tmp_path / "storage"),
            "SAABIT_SAMPLE_CACHE": str(tmp_path / "cache"),
            "GROQ_BASE_URL": start_llm_stub(),
            "GROQ_API_KEY": STUB_KEY,
        }
        print(f"25 MB upload file: {upload.stat().st_size:,} bytes; budget {BUDGET_MB} MB peak "
              f"at runtime, {BUILD_BUDGET_MB} MB for the image-build step\n")
        print(f"{'scenario':<16}{'peak RSS':>10}  {'budget':<12}{'result'}")
        over = False
        for name, description in SCENARIOS.items():
            result = spawn(name, env, upload if name.endswith("_25mb") else None)
            budget = BUILD_BUDGET_MB if name == "prepare_sample" else BUDGET_MB
            ok = result["peak_mb"] < budget
            over |= not ok
            verdict = f"{'OK' if ok else 'OVER'} <{budget}"
            print(f"{name:<16}{result['peak_mb']:>7.0f} MB  {verdict:<12}"
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
