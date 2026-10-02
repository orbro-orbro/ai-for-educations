from __future__ import annotations

import sys

from runner.worker.executor import execute
from runner.worker.protocol import MAX_SOURCE_BYTES, RunnerRequest


MAX_REQUEST_BYTES = MAX_SOURCE_BYTES + 256 * 1024


def main() -> int:
    payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(payload) > MAX_REQUEST_BYTES:
        print("request exceeds sandbox input limit", file=sys.stderr)
        return 2
    try:
        request = RunnerRequest.model_validate_json(payload)
        result = execute(request)
    except Exception as exc:
        print(f"invalid runner request: {type(exc).__name__}", file=sys.stderr)
        return 2
    sys.stdout.write(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
