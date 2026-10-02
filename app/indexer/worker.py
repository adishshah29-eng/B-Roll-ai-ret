"""Indexer worker: drains the job queue. Run standalone (CLI) or as a thread inside the API server.

    python -m app.indexer.worker --path footage          # enqueue a folder, process, exit
    python -m app.indexer.worker --watch                 # keep polling for jobs
"""
import argparse
import threading
import time
import traceback

import torch

from .. import db
from ..config import FOOTAGE
from . import jobs, pipeline, tags

_state = {"running": False, "current": "", "done": 0, "errors": 0}
_stop = threading.Event()


def state() -> dict:
    return dict(_state)


def run_job(job) -> dict:
    stage = job["stage"]
    if stage == jobs.STAGE_INDEX:
        return pipeline.index_file(job["target_id"])
    # later stages (cutfeat, ocr) are registered by their phases
    handler = STAGE_HANDLERS.get(stage)
    if handler is None:
        return {"status": "skipped"}
    return handler(job["target_id"])


STAGE_HANDLERS = {}


def drain(verbose=True) -> int:
    n = 0
    while not _stop.is_set():
        job = jobs.claim()
        if job is None:
            break
        label = f"{job['stage']}#{job['target_id']}"
        _state.update(running=True, current=label)
        t0 = time.time()
        try:
            r = run_job(job)
            jobs.complete(job["id"])
            _state["done"] += 1
            n += 1
            if verbose:
                print(f"[ok] {label} {r} in {time.time()-t0:.1f}s", flush=True)
        except Exception as e:  # keep the queue moving
            jobs.fail(job["id"], f"{type(e).__name__}: {e}")
            _state["errors"] += 1
            if verbose:
                print(f"[err] {label}: {e}", flush=True)
                traceback.print_exc()
    _state.update(running=False, current="")
    return n


def loop(poll_s=2.0):
    """Thread target for the API server."""
    jobs.reset_stale()
    tags.ensure_caches()
    while not _stop.is_set():
        if drain(verbose=False) == 0:
            _stop.wait(poll_s)


def start_thread():
    _stop.clear()
    t = threading.Thread(target=loop, name="indexer", daemon=True)
    t.start()
    return t


def stop():
    _stop.set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None, help="folder of videos to enqueue")
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    torch.set_num_threads(max(1, (torch.get_num_threads() or 4) - 1))
    db.conn()
    jobs.reset_stale()
    print("building prompt/vocab caches (first run loads CLIP)...", flush=True)
    tags.ensure_caches()
    if a.path:
        print("enqueue:", jobs.enqueue_folder(a.path), flush=True)
    t0 = time.time()
    n = drain()
    print(f"processed {n} jobs in {time.time()-t0:.1f}s | queue: {jobs.status()}", flush=True)
    while a.watch:
        time.sleep(2)
        drain()


if __name__ == "__main__":
    main()
