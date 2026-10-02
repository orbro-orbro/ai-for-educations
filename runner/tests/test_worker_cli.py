import io
import sys

from runner.worker import cli
from runner.worker.protocol import (
    CommandSummary,
    RunnerLimits,
    RunnerPhase,
    RunnerRequest,
    RunnerResult,
    RunnerStatus,
    ToolchainInfo,
)


class _OpenStdin(io.BytesIO):
    """Docker keeps an attached sandbox stdin open after the controller half-closes its socket."""

    def read(self, size=-1):
        data = super().read(size)
        if self.tell() >= len(self.getvalue()):
            raise AssertionError("worker waited for stdin EOF instead of stopping at the request frame")
        return data


def test_worker_reads_one_newline_framed_request_without_waiting_for_eof(monkeypatch, capsys):
    request = RunnerRequest(
        submission_id="framed",
        source_files=[{"path": "main.cj", "content": 'main() {\n    println("a\\nb")\n}\n'}],
        entrypoint="main.cj",
        timeout_ms=1_000,
    )
    seen = []

    def fake_execute(received):
        seen.append(received)
        return RunnerResult(
            submission_id=received.submission_id,
            status=RunnerStatus.succeeded,
            phase=RunnerPhase.run,
            retryable=False,
            exit_code=0,
            signal=None,
            stdout="",
            stderr="",
            diagnostics=[],
            command_summary=CommandSummary(source_count=1, entrypoint="main.cj"),
            limits=RunnerLimits(timeout_ms=1_000),
            toolchain=ToolchainInfo(),
        )

    stdin = _OpenStdin(request.model_dump_json().encode() + b"\n")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(stdin))
    monkeypatch.setattr(cli, "execute", fake_execute)

    assert cli.main() == 0
    assert seen == [request]
    assert RunnerResult.model_validate_json(capsys.readouterr().out).submission_id == "framed"
