"""Teacher-local launcher and kit tests use stub commands only; never run real Docker."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# Teachers usually only have the Windows PowerShell 5.1 that ships with Windows.
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "Windows launcher tests need PowerShell")
class TeacherLocalLauncherTests(unittest.TestCase):
    def invoke(self, *, docker=True, info_exit=0, os_type="linux", start_fail=False, web_status=200):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy(ROOT / "scripts/start-teacher-local.ps1", scripts)
            calls = root / "calls.jsonl"
            (scripts / "start-delivery.ps1").write_text(
                'param([string]$Action="Start",[switch]$NoBuild,[switch]$FreshData,[switch]$TeacherTest)\n'
                '[pscustomobject]@{kind="delivery";action=$Action;build=-not $NoBuild;fresh=[bool]$FreshData;teacher=[bool]$TeacherTest} | ConvertTo-Json -Compress | Add-Content $env:KIT_CALLS\n'
                'if($env:KIT_START_FAIL -eq "1") { throw "Demo services did not reach healthy state" }\n'
                'function global:Invoke-WebRequest { param($Uri,$TimeoutSec,[switch]$UseBasicParsing) '
                'if(-not $UseBasicParsing) { throw "Windows PowerShell 5.1 needs -UseBasicParsing" } '
                '[pscustomobject]@{StatusCode=[int]$env:KIT_WEB_STATUS} }\n', encoding="utf-8")
            stub = root / "stub.py"
            stub.write_text(
                'import json,os,sys\n'
                'with open(os.environ["KIT_CALLS"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'if "--format" in sys.argv: print(os.environ["KIT_OS_TYPE"])\n'
                'sys.exit(int(os.environ["KIT_INFO_EXIT"]))\n', encoding="utf-8")
            if docker:
                (root / "docker.cmd").write_text(f'@"{os.sys.executable}" "{stub}" docker %*\n', encoding="utf-8")
            env = {**os.environ, "PATH": str(root) + os.pathsep + str(SYSTEM32),
                   "KIT_CALLS": str(calls), "KIT_INFO_EXIT": str(info_exit), "KIT_OS_TYPE": os_type,
                   "KIT_START_FAIL": "1" if start_fail else "0", "KIT_WEB_STATUS": str(web_status)}
            result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(scripts / "start-teacher-local.ps1"), "-NoBrowser", "-WebWaitSeconds", "2"],
                                    capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=60)
            lines = calls.read_text().splitlines() if calls.exists() else []
            delivery = [json.loads(line) for line in lines if line.startswith("{")]
            return result, delivery, result.stdout + result.stderr

    def test_missing_docker_stops_with_install_guidance_before_anything_starts(self):
        result, delivery, output = self.invoke(docker=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DOCKER_MISSING", output)
        self.assertEqual(delivery, [])
        self.assertNotIn("TEACHER_LOCAL_READY", output)

    def test_docker_desktop_not_started_stops_before_starting_demo(self):
        result, delivery, output = self.invoke(info_exit=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DOCKER_NOT_RUNNING", output)
        self.assertEqual(delivery, [])

    def test_windows_containers_are_rejected(self):
        result, delivery, output = self.invoke(os_type="windows")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DOCKER_NOT_LINUX", output)
        self.assertEqual(delivery, [])

    def test_failed_start_never_prints_a_success_message(self):
        result, delivery, output = self.invoke(start_fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("START_FAILED", output)
        self.assertNotIn("TEACHER_LOCAL_READY", output)

    def test_web_that_is_not_ready_is_reported_not_hidden(self):
        result, delivery, output = self.invoke(web_status=500)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WEB_NOT_READY", output)
        self.assertNotIn("TEACHER_LOCAL_READY", output)

    def test_success_starts_the_normal_demo_only_and_reports_the_local_address(self):
        result, delivery, output = self.invoke()
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("TEACHER_LOCAL_READY", output)
        self.assertIn("http://127.0.0.1:5209", output)
        self.assertEqual(len(delivery), 1)
        self.assertEqual(delivery[0]["action"], "Start")
        self.assertFalse(delivery[0]["teacher"], "the local teacher path must not use the tunnel build")
        self.assertFalse(delivery[0]["fresh"], "never reset data implicitly")


@unittest.skipUnless(shutil.which("git") and POWERSHELL, "Kit tests need git and PowerShell")
class TeacherKitPackageTests(unittest.TestCase):
    def build_repo(self, root, tracked_extra=()):
        files = {
            "backend/app/main.py": "print('api')\n", "frontend/package.json": "{}\n", "runner/Dockerfile": "FROM scratch\n",
            "infra/compose/docker-compose.yml": "services: {}\n", "scripts/start-delivery.ps1": "# stub\n",
            "start-teacher-local.cmd": "@echo off\n", "docs/teacher-guide.md": "# guide\n",
            "docs/superpowers/spec.md": "internal\n", "requirment.docx": "binary\n", ".gitignore": ".delivery/\n.env\nnode_modules/\n",
        }
        files.update({path: "x\n" for path in tracked_extra})
        for relative, text in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        shutil.copy(ROOT / "scripts/package-teacher-kit.ps1", root / "scripts")
        for command in (["init", "-q"], ["add", "-A", "-f", "--", "."], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", *command], cwd=root, check=True, capture_output=True)
        # Ignored local secrets and caches that must never travel in the kit.
        for relative in (".delivery/demo.env", ".delivery/live-model.env", ".env", "frontend/node_modules/pkg/index.js"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("SECRET=must-not-ship\n", encoding="utf-8")

    def package(self, tracked_extra=()):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            root.mkdir()
            self.build_repo(root, tracked_extra)
            output = Path(folder) / "kit.zip"
            result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(root / "scripts/package-teacher-kit.ps1"), "-OutputPath", str(output)],
                                    capture_output=True, encoding="utf-8", errors="replace", cwd=root, timeout=120)
            names = zipfile.ZipFile(output).namelist() if output.exists() else None
            return result, names

    def test_kit_contains_only_what_is_needed_to_run_and_no_local_secrets(self):
        result, names = self.package()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        joined = "\n".join(names)
        for required in ("backend/app/main.py", "frontend/package.json", "runner/Dockerfile", "infra/compose/docker-compose.yml",
                         "scripts/start-delivery.ps1", "start-teacher-local.cmd", "docs/teacher-guide.md"):
            self.assertIn(required, joined)
        for forbidden in (".delivery", ".env", "node_modules", ".git/", "superpowers", "requirment.docx", "must-not-ship"):
            self.assertNotIn(forbidden, joined)

    def test_a_tracked_secret_or_dependency_folder_makes_packaging_fail_and_leaves_no_archive(self):
        for extra in ("backend/.env", "frontend/node_modules/leak/index.js", "scripts/live-model.env"):
            with self.subTest(extra=extra):
                result, names = self.package((extra,))
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(names, "a refused kit must not be left on disk")


if __name__ == "__main__":
    unittest.main()
