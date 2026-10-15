"""Bounded experiment driver. Host sends JSON; all source stays in sandboxes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from threading import Event, Thread
import time
from urllib.request import Request, urlopen
from uuid import uuid4
import docker

SCENARIOS = (
    ("success", 'main() { println("synthetic stability success") }', "succeeded"),
    ("compile_failure", "main() { let x: Int64 = true }", "compile_failed"),
    ("timeout", "main() { while (true) {} }", "timed_out"),
    ("output_limit", 'main() { while (true) { println("0123456789abcdef0123456789abcdef") } }', "timed_out"),
    ("success_after_timeout", 'main() { println("synthetic cleanup success") }', "succeeded"),
)
IMAGE = "knowbound-wave4-test-sandbox:task11"
ENDPOINT = "http://127.0.0.1:8209/v2/execute"


def schedule():
    return [(concurrency, round_number, scenario, source, expected)
        for concurrency in (1, 2) for round_number in (1, 2, 3)
        for scenario, source, expected in SCENARIOS]


def run_stability(output_dir):
    if os.environ.get("WAVE4_TEST_MODE") != "1":
        raise ValueError("Explicit Task 11 test selection required")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    client = docker.from_env(timeout=5)
    controller = client.containers.get("knowbound-wave4-test-runner-controller-1")
    labels = controller.labels
    if labels.get("com.docker.compose.project") != "knowbound-wave4-test" or labels.get("knowbound.task") != "wave4-task11-test":
        raise ValueError("Refuse a foreign controller")
    if "RUNNER_SANDBOX_IMAGE=" + IMAGE not in controller.attrs["Config"]["Env"]:
        raise ValueError("Controller must select the dedicated Task 11 sandbox image")
    def own_containers():
        rows = []
        for item in client.containers.list(all=True, sparse=True, filters={"label":"knowbound.component=cangjie-sandbox"}):
            try:
                item.reload()
                if item.attrs["Config"]["Image"] == IMAGE: rows.append(item)
            except docker.errors.NotFound:
                pass  # Expected race with the controller's completed-job removal.
        return rows
    before = {c.id for c in own_containers()}
    if before:
        raise ValueError("Experiment requires no existing Task 11 sandbox jobs")
    started = datetime.now(UTC)
    deadline = time.monotonic() + 240
    stopped = Event()
    snapshots, monitor_errors, results, events = [], [], [], []
    event_stream = client.events(since=started.timestamp(), decode=True,
        filters={"label":"knowbound.component=cangjie-sandbox"})
    def collect_events():
        try:
            for event in event_stream:
                if event.get("Actor",{}).get("Attributes",{}).get("image") == IMAGE:
                    events.append(event)
        except Exception as error:
            if not stopped.is_set(): monitor_errors.append("events:" + type(error).__name__)
    event_observer = Thread(target=collect_events, daemon=True)
    event_observer.start()
    def monitor():
        while not stopped.is_set():
            try:
                containers = own_containers()
                for container in containers:
                    try:
                        container.reload()
                        attrs = container.attrs
                        config = attrs["HostConfig"]
                        row = {"id":container.id, "at":datetime.now(UTC).isoformat(), "simultaneous":len(containers),
                            "user":attrs["Config"]["User"], "network":config["NetworkMode"], "read_only":config["ReadonlyRootfs"],
                            "memory":config["Memory"], "nano_cpus":config["NanoCpus"], "pids_limit":config["PidsLimit"],
                            "cap_drop":config["CapDrop"], "security_opt":config["SecurityOpt"], "tmpfs":config["Tmpfs"],
                            "oom_killed":attrs["State"].get("OOMKilled",False)}
                        stats = container.stats(stream=False, one_shot=True)
                        row.update(memory_usage=stats.get("memory_stats",{}).get("usage"),
                            pids_current=stats.get("pids_stats",{}).get("current"), cpu_usage=stats.get("cpu_stats",{}).get("cpu_usage",{}).get("total_usage"))
                        snapshots.append(row)
                    except docker.errors.NotFound:
                        pass
            except Exception as error:
                monitor_errors.append(type(error).__name__)
            stopped.wait(.1)
    def execute(concurrency, round_number, scenario, source, expected, replica):
        sid = "synthetic-wave4-stability-" + uuid4().hex
        body = {"protocol_version":"2", "submission_id":sid, "source_files":[{"path":"main.cj","content":source}], "entrypoint":"main.cj", "timeout_ms":5000}
        start = time.monotonic()
        row = {"concurrency":concurrency, "round":round_number, "scenario":scenario, "replica":replica, "submission_id":sid, "expected":expected}
        try:
            request = Request(ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
            with urlopen(request, timeout=25) as response:
                result = json.load(response)
            row["result"] = result
            row["passed"] = result["status"] == expected and result["submission_id"] == sid and result["toolchain"]["cjc"] == "1.2.0" and result["toolchain"]["cjpm"] == "1.2.0"
            if scenario == "output_limit":
                row["passed"] &= result["stdout_truncated"] and len(result["stdout"]) == 65536
            if scenario == "compile_failure":
                row["passed"] &= bool(result["diagnostics"])
            if scenario in {"success", "success_after_timeout"}:
                row["passed"] &= "synthetic" in result["stdout"]
        except Exception as error:
            row.update(passed=False, error_type=type(error).__name__)
        row["duration_seconds"] = time.monotonic() - start
        return row
    observer = Thread(target=monitor, daemon=True)
    observer.start()
    try:
        for concurrency, round_number, scenario, source, expected in schedule():
            if time.monotonic() >= deadline:
                raise TimeoutError("Bounded experiment deadline exceeded")
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(execute, concurrency, round_number, scenario, source, expected, replica) for replica in range(concurrency)]
                results.extend(future.result(timeout=30) for future in futures)
    finally:
        event_deadline = time.monotonic() + 2
        while time.monotonic() < event_deadline and len([e for e in events if e.get("Action") == "destroy"]) < len(results):
            time.sleep(.05)
        stopped.set()
        event_stream.close()
        event_observer.join(timeout=5)
        observer.join(timeout=10)
        finished = datetime.now(UTC)
        after = {c.id for c in own_containers()}
        created = {event["Actor"]["ID"] for event in events if event.get("Action") == "create"}
        destroyed = {event["Actor"]["ID"] for event in events if event.get("Action") == "destroy"}
        limits_ok = bool(snapshots) and all(row["simultaneous"] <= 2 and row["user"] == "10001:10001" and row["network"] == "none"
            and row["read_only"] and row["memory"] == 512*1024*1024 and row["nano_cpus"] == 1_000_000_000 and row["pids_limit"] == 64
            and row["cap_drop"] == ["ALL"] and any("no-new-privileges" in value for value in row["security_opt"]) and "/work" in row["tmpfs"] for row in snapshots)
        durations = sorted(row["duration_seconds"] for row in results)
        report = {"data_nature":"synthetic only; finite workload does not establish historical root cause or production stability",
            "head":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
            "started_utc":started.isoformat(), "finished_utc":finished.isoformat(), "endpoint":ENDPOINT,
            "image_id":client.images.get(IMAGE).id, "timeout_ms":5000, "overall_deadline_seconds":240,
            "results":results, "snapshots":snapshots, "events":events, "monitor_errors":monitor_errors,
            "containers_before":sorted(before), "containers_after":sorted(after), "created":sorted(created), "destroyed":sorted(destroyed),
            "limits_verified":limits_ok, "latency_seconds":{"p50":durations[len(durations)//2] if durations else None,
                "p95":durations[min(len(durations)-1,int(len(durations)*.95))] if durations else None,"max":max(durations,default=None)}}
        (output_dir / "stability.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        client.close()
    assert len(results) == 45 and all(row["passed"] for row in results), "Unexpected outcome; raw diagnostics retained in stability.json"
    assert limits_ok and not monitor_errors, "Resource observation incomplete or unsafe"
    assert len(created) == 45 and created == destroyed and not after, "Container cleanup evidence incomplete"
    return report
