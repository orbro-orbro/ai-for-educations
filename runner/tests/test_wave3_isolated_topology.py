"""Host submits JSON only; every Cangjie execution is in controller jobs."""
import json
import os
from urllib.request import Request, urlopen
from uuid import uuid4
import pytest
import docker


@pytest.mark.parametrize("scenario,source,expected",[
    ("success",'main() { println("synthetic gate hello") }',"succeeded"),
    ("compiler_failure","main() { let x: Int64 = true }","compile_failed"),
    ("infinite_loop","main() { while (true) {} }","timed_out"),
    ("output_limit",'main() { while (true) { println("0123456789abcdef0123456789abcdef") } }',"timed_out"),
])
def test_real_controller_launches_and_cleans_isolated_job(scenario,source,expected,record_property):
    client=docker.from_env()
    before={c.id for c in client.containers.list(all=True,filters={"label":"knowbound.component=cangjie-sandbox"})}
    body={"protocol_version":"2","submission_id":"synthetic-gate-"+uuid4().hex,
        "source_files":[{"path":"main.cj","content":source}],"entrypoint":"main.cj","timeout_ms":2000}
    endpoint = "http://127.0.0.1:8209" if os.environ.get("WAVE4_TEST_MODE") == "1" else "http://127.0.0.1:8199"
    request=Request(endpoint + "/v2/execute",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    with urlopen(request,timeout=25) as response:
        assert response.status==200
        result=json.load(response)
    assert result["submission_id"]==body["submission_id"]
    record_property('actual_status',result['status'])
    record_property('phase',result['phase'])
    record_property('exit_code',result['exit_code'])
    assert result["status"]==expected, {k:result[k] for k in ('status','phase','exit_code','signal','stderr','diagnostics')}
    assert result["protocol_version"]=="2"
    assert "1.2.0" in result["toolchain"]["cjc"]
    assert result["limits"]["pids"]==64
    assert len(result["stdout"])<=65536 and len(result["stderr"])<=65536
    if scenario=="success":assert result["stdout"].strip()=="synthetic gate hello"
    if scenario=="compiler_failure":assert result["diagnostics"]
    if scenario=="output_limit":assert result["stdout_truncated"] and len(result["stdout"])==65536
    after={c.id for c in client.containers.list(all=True,filters={"label":"knowbound.component=cangjie-sandbox"})}
    assert after <= before, "controller left a new sandbox container behind"
    client.close()
