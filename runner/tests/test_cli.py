import io
import sys

from runner.worker.cli import MAX_REQUEST_BYTES, _read_payload
from runner.worker.protocol import MAX_FILE_BYTES, MAX_FILES, MAX_PATH_BYTES, RunnerRequest


def test_request_is_read_as_one_bounded_json_line(monkeypatch):
    payload = b'{"submission_id":"sub-1"}'
    stdin = type("Input", (), {"buffer": io.BytesIO(payload + b"\nignored")})()
    monkeypatch.setattr(sys, "stdin", stdin)

    assert _read_payload() == payload


def test_largest_valid_request_fits_the_worker_input_frame():
    files = []
    for index in range(MAX_FILES):
        suffix = f"-{index}.cj"
        path = ("a" * (MAX_PATH_BYTES - len(suffix))) + suffix
        content = "x" * MAX_FILE_BYTES if index < 4 else ""
        files.append({"path": path, "content": content})
    request = RunnerRequest(
        submission_id="max-frame",
        source_files=files,
        entrypoint=files[0]["path"],
        timeout_ms=30_000,
    )

    assert len(request.model_dump_json().encode("utf-8")) < MAX_REQUEST_BYTES
