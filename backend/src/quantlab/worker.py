"""The backtest worker: ``python -m quantlab.worker``.

Runs queued backtests (research.jobs) in a process of its own, so a run that
exhausts memory takes down this container, never the API. Uses the same store
selection as the API -- the warehouse when QUANTLAB_DB_URL and QUANTLAB_CH_URL
are set, else the demo database -- so the two always agree on where runs live.
"""

from __future__ import annotations

import signal
import threading

from quantlab.api.app import resolve_db_path
from quantlab.logging import get_logger
from quantlab.research import jobs
from quantlab.storage import backends, experiments

logger = get_logger(__name__)


def main() -> None:
    db_path = resolve_db_path()
    backend = backends.select_backend(db_path)
    store = experiments.select_experiment_store(db_path, wh=getattr(backend, "wh", None))
    worker = jobs.Worker(backend, store)

    stopping = threading.Event()

    def stop(signum, _frame) -> None:
        # SIGTERM from `docker compose` on a deploy. The running run is left
        # as it is: its lease lapses and the next worker queues it again.
        logger.info("run_worker_stopping", extra={"signal": signum})
        stopping.set()
        worker.stop(timeout=1)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    worker.start()
    while not stopping.wait(jobs.LEASE_SECONDS):
        worker._recover()


if __name__ == "__main__":
    main()
