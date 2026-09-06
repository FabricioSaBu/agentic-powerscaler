"""
Live progress for long-running pipeline requests.

The HUD used to advance on fixed timers, which meant the labels were plausible fiction:
a step could sit spinning after its work had finished, or the last step could hold while
real work continued. This publishes what is *actually* happening.

The run id travels in a ContextVar rather than through every function signature: agents
report via BaseAgent.log(), which has no access to request state, and contextvars propagate
correctly across awaits within a single request.
"""

from collections import OrderedDict
from contextvars import ContextVar
from threading import Lock
from time import time
from typing import Dict, List, Optional

# Set per request by the web routes; None on the JSON API path, where nothing is watching.
current_run: ContextVar[Optional[str]] = ContextVar("current_run", default=None)

_MAX_RUNS = 40      # in-memory only; old runs are evicted rather than accumulating
_MAX_STEPS = 80     # a runaway loop can't grow one run without bound


class ProgressStore:
    def __init__(self) -> None:
        self._runs: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = Lock()

    def publish(self, run_id: Optional[str], message: str) -> None:
        if not run_id or not message:
            return
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                run = {"steps": [], "done": False, "updated": time()}
                self._runs[run_id] = run
                while len(self._runs) > _MAX_RUNS:
                    self._runs.popitem(last=False)
            self._runs.move_to_end(run_id)
            steps: List[dict] = run["steps"]
            # Collapse immediate repeats (e.g. the same skip message per contender).
            if steps and steps[-1]["message"] == message:
                return
            steps.append({"message": message, "at": time()})
            del steps[:-_MAX_STEPS]
            run["updated"] = time()

    def finish(self, run_id: Optional[str]) -> None:
        if not run_id:
            return
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run["done"] = True
                run["updated"] = time()

    def snapshot(self, run_id: str) -> Dict:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return {"steps": [], "done": False}
            return {"steps": list(run["steps"]), "done": run["done"]}


progress = ProgressStore()


def report(message: str) -> None:
    """Publish to whichever run is active on this request, if any."""
    progress.publish(current_run.get(), message)
