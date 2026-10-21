"""Launcher tests use stub commands only; never run Docker or open a tunnel."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
# Teachers may only have the Windows PowerShell 5.1 that ships with Windows.
SHELLS = [path for path in (shutil.which("powershell"), shutil.which("pwsh")) if path]


class TeacherLauncherTests(unittest.TestCase):
    def invoke(self, email="teacher@example.com", supported=True, shell=None):
        shell = shell or SHELLS[0]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy(ROOT / "scripts/start-teacher-test.ps1", scripts)
            calls = root / "calls.jsonl"
            (scripts / "start-delivery.ps1").write_text(
                'param([switch]$TeacherTest,[switch]$NoBuild,[switch]$FreshData)\n'
                '[pscustomobject]@{kind="delivery";teacher=[bool]$TeacherTest;fresh=[bool]$FreshData} | ConvertTo-Json -Compress | Add-Content $env:TEACHER_TEST_CALLS\n'
                'function global:Invoke-WebRequest { param($Uri,$TimeoutSec,[switch]$UseBasicParsing) if(-not $UseBasicParsing) { throw "Windows PowerShell 5.1 needs -UseBasicParsing" } [pscustomobject]@{StatusCode=200;Headers=@{"Content-Type"="application/json"}} }\n', encoding="utf-8")
            stub = root / "stub.py"
            stub.write_text(
                'import json,os,sys\n'
                'with open(os.environ["TEACHER_TEST_CALLS"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'if "--help" in sys.argv: print("--allowed-mail" if os.environ["TEACHER_TEST_SUPPORTED"]=="1" else "old client")\n', encoding="utf-8")
            self.assertEqual(os.name, "nt", "Acceptance harness currently targets the Windows launcher")
            for name in ("cloudflared", "docker"):
                (root / f"{name}.cmd").write_text(f'@"{os.sys.executable}" "{stub}" {name} %*\n', encoding="utf-8")
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "TEACHER_TEST_CALLS": str(calls), "TEACHER_TEST_SUPPORTED": "1" if supported else "0"}
            result = subprocess.run([shell, "-NoProfile", "-File", str(scripts / "start-teacher-test.ps1"),
                                     "-AllowedEmail", email, "-FreshData"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
            return result, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def test_rejects_wildcard_before_starting_anything(self):
        result, calls = self.invoke("*@example.com")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_unsupported_client_never_falls_back_to_public_access(self):
        result, calls = self.invoke(supported=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(isinstance(call, dict) for call in calls))
        self.assertFalse(any("--url" in call for call in calls))

    def test_passes_only_web_origin_email_and_preserving_reset(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn({"kind": "delivery", "teacher": True, "fresh": True}, calls)
        self.assertIn(["cloudflared", "tunnel", "--url", "http://127.0.0.1:5209", "--allowed-mail", "teacher@example.com"], calls)


if __name__ == "__main__":
    unittest.main()
