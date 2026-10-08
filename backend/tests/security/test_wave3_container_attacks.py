"""Planned Cangjie attacks execute only in the fixed hardened SDK sandbox."""
import re
import json
import os
import subprocess
import time
from uuid import uuid4
import docker
import pytest
from .test_isolated_runner import isolated_execute

NETWORK='''import std.net.*
main() {
  println("NETWORK_ATTEMPT")
  try {
    let socket = TcpSocket("203.0.113.1", 443u16)
    socket.connect(timeout: Duration.millisecond * 200)
    println("NETWORK_CONNECTED")
    socket.close()
  } catch (e: Exception) { println("NETWORK_DENIED") }
}'''
PID='''import std.process.*
import std.collection.*
main() {
  let children = ArrayList<SubProcess>()
  try {
    while (children.size < 128) { children.add(launch("/bin/sleep", ["30"])) }
    println("PID_UNBOUNDED")
  } catch (e: Exception) { println("PID_DENIED:${children.size}") }
  for (child in children) { child.terminate(force: true) }
}'''
OUTPUT='''main() { while (true) { println("0123456789abcdef0123456789abcdef") } }'''

def observed_pid_attack(source):
    """Read kernel-backed Docker PID stats without starting extra worker processes."""
    name='knowbound-wave3-pid-'+uuid4().hex
    client=docker.from_env()
    request={'protocol_version':'2','submission_id':'synthetic-pid','source_files':[{'path':'main.cj','content':source}],
             'entrypoint':'main.cj','timeout_ms':10000}
    command=['docker','run','--rm','--name',name,'--label','knowbound.task=wave3-integration-gate','-i',
        '--network','none','--read-only','--user','10001:10001','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--pids-limit','64','--memory','512m','--cpus','1',
        '--tmpfs','/work:rw,nosuid,nodev,exec,size=64m,mode=0700,uid=10001,gid=10001',
        '--entrypoint','python',os.environ['TASK10_RUNNER_IMAGE'],'-m','runner.worker.cli']
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    process.stdin.write(json.dumps(request)+'\n');process.stdin.close();process.stdin=None
    counts=[];configured_limit=None;deadline=time.monotonic()+30
    try:
        while process.poll() is None and time.monotonic()<deadline:
            try:
                container=client.containers.get(name)
                configured_limit=container.attrs['HostConfig']['PidsLimit']
                counts.append(container.stats(stream=False,one_shot=True)['pids_stats'].get('current',0))
            except docker.errors.NotFound:pass
            time.sleep(.05)
        output,error=process.communicate(timeout=5)
        assert process.returncode==0,error
        return json.loads(output),counts,configured_limit
    finally:
        if process.poll() is None:process.kill();process.communicate()
        subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=10)
        client.close()

@pytest.mark.parametrize('case_id,source',[
    ('sec-executor-abuse-006',NETWORK),('sec-executor-abuse-007',PID),('sec-executor-abuse-008',OUTPUT)
],ids=['sec-executor-abuse-006','sec-executor-abuse-007','sec-executor-abuse-008'])
def test_concrete_container_attack(case_id,source,record_property):
    if case_id.endswith('007'):
        result,counts,limit=observed_pid_attack(source)
        record_property('observed_pid_counts',json.dumps(counts))
        assert limit==64 and counts and max(counts)==64 and all(n<=64 for n in counts)
    else:result=isolated_execute(source,timeout_ms=5000)
    record_property('case_id',case_id)
    record_property('actual_status',result['status'])
    record_property('actual_stdout',result['stdout'])
    assert result['toolchain']['cjc']=='1.2.0' and result['toolchain']['cjpm']=='1.2.0'
    assert result['status']!='compile_failed',result['diagnostics']
    if case_id.endswith('006'):
        assert result['status']=='succeeded'
        assert 'NETWORK_ATTEMPT' in result['stdout'] and 'NETWORK_DENIED' in result['stdout']
        assert 'NETWORK_CONNECTED' not in result['stdout']
    elif case_id.endswith('007'):
        assert 'PID_UNBOUNDED' not in result['stdout']
        # The SDK can block trying to create runtime threads at the PID cap.
        # Either an explicit launch rejection or the deadline is a bounded outcome;
        # actual cap exhaustion is proved above by cgroup-backed PID telemetry.
        assert result['status'] in ('succeeded','timed_out')
        if result['status']=='succeeded':
            match=re.search(r'PID_DENIED:(\d+)',result['stdout']);assert match,result
            assert 0<int(match.group(1))<64
    else:
        assert result['status']=='timed_out' and result['stdout_truncated']
        assert len(result['stdout'])==65536 and len(result['stderr'])<=65536
