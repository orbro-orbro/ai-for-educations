"""Fail closed on a foreign named container, even without Compose labels."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_launcher_refuses_unlabeled_name_collision_before_build_or_start(tmp_path):
    root = Path(__file__).resolve().parents[3]
    log = tmp_path / "calls.txt"
    stub = tmp_path / "docker_stub.py"
    stub.write_text('''import json, os, sys
args=sys.argv[1:]
with open(os.environ['DELIVERY_STUB_LOG'],'a') as f: f.write(json.dumps(args)+'\\n')
if args[:2]==['ps','-aq'] and any(a.startswith('name=') for a in args): print('synthetic-foreign-container')
elif args and args[0]=='inspect': print(json.dumps({'com.docker.compose.project':'foreign-daily-project'}))
''', encoding="utf-8")
    if os.name == "nt":
        (tmp_path / "docker.cmd").write_text(f'@"{sys.executable}" "{stub}" %*\n', encoding="utf-8")
    else:
        executable = tmp_path / "docker"
        executable.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n', encoding="utf-8")
        executable.chmod(0o755)
    env = {**os.environ, "PATH":str(tmp_path)+os.pathsep+os.environ["PATH"], "DELIVERY_STUB_LOG":str(log)}
    shell = shutil.which("pwsh")
    assert shell, "PowerShell is required for the delivery launcher acceptance test"
    result = subprocess.run([shell, "-NoProfile", "-File", str(root / "scripts/start-delivery.ps1")],
        env=env, text=True, encoding="utf-8", capture_output=True, timeout=30)
    assert result.returncode != 0, "Launcher accepted a foreign named resource"
    assert "Refuse to modify a foreign container" in result.stderr
    import json
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any("build" in call or "up" in call or "stop" in call for call in calls)
