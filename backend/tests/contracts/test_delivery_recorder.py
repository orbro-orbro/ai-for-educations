import json
from pathlib import Path
import shutil
import subprocess


def test_silent_success_has_a_hashed_empty_log_and_real_exit_record(tmp_path):
    root = Path(__file__).resolve().parents[3]
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required for the delivery recorder acceptance test"
    # Docker tag/config and git checks can succeed with no output. Exercise that
    # exact native behavior separately using a tiny trusted executable wrapper.
    script = tmp_path/"silent.ps1"
    script.write_text("exit 0\n")
    command = f"& '{root.as_posix()}/scripts/record-delivery-command.ps1' -Name empty -Executable '{Path(shell).as_posix()}' -CommandArguments @('-NoProfile','-File','{script.as_posix()}') -WorkingDirectory '{root.as_posix()}' -EvidenceDirectory '{(tmp_path/'evidence').as_posix()}'"
    result = subprocess.run([shell,"-NoProfile","-Command",command],capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert result.returncode == 0, result.stderr
    path = next((tmp_path/"evidence").glob("empty-*/command.json"))
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    assert record["exit_code"] == 0 and (path.parent/"output.log").read_bytes() == b""
    assert record["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
