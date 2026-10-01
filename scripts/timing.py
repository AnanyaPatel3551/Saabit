"""Time to numbers and time to sentence for a few questions, end to end over HTTP.

Starts the app in-process on a free port, with a fresh plan cache so nothing is pre-planned,
loads the sample, then for each question: POST /plan, POST /run (time to numbers), then POST
/api/cards/{id}/sentence (time to sentence). Uses whatever LLM_PROVIDERS says.

Usage (from the repo root, with keys in the environment):
    python scripts/timing.py "question one" "question two" ...
"""

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(questions: list[str]) -> int:
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("SAABIT_PLAN_CACHE", tempfile.mkdtemp(prefix="saabit-timing-"))
    import httpx
    import uvicorn
    from app.main import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    sample = httpx.post(f"{base}/api/datasets/sample", timeout=120).json()["dataset_id"]
    print(f"providers: {os.environ.get('LLM_PROVIDERS', 'groq,nim')}")
    print(f"{'question':<42} {'numbers':>9} {'sentence':>9}  plan from / sentence from")
    for question in questions:
        start = time.perf_counter()
        planned = httpx.post(f"{base}/api/datasets/{sample}/plan", json={"question": question},
                             timeout=120).json()
        if planned.get("plan", {}).get("status") != "ok":
            print(f"{question:<42} not planned: {str(planned)[:80]}")
            continue
        run = httpx.post(f"{base}/api/datasets/{sample}/run", json=planned["plan"],
                         timeout=120).json()
        numbers = time.perf_counter() - start
        written = httpx.post(f"{base}/api/cards/{run['card']['card_id']}/sentence",
                             json={"question": question}, timeout=120).json()
        sentence = time.perf_counter() - start
        origin = "saved plan" if planned["cached"] else "LLM"
        print(f"{question:<42} {numbers:>8.2f}s {sentence:>8.2f}s  {origin} / {written['source']}")
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
