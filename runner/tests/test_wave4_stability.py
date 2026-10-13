"""Host orchestrates JSON requests only; every compile/run is isolated."""
import os
from pathlib import Path
from uuid import uuid4
from scripts.runner_stability import run_stability


def test_bounded_repeated_real_runner_stability(tmp_path):
    base = Path(os.environ.get("TASK11_STABILITY_EVIDENCE", str(tmp_path)))
    report = run_stability(base / ("runner-stability-" + uuid4().hex))
    assert len(report["results"]) == 45
    assert report["limits_verified"]
    assert report["containers_after"] == []
