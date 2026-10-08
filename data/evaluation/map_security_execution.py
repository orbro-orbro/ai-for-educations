"""Join immutable planned cases to actual per-parameter JUnit evidence.

This does not modify draft annotations or invent teaching observations.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
STATUSES={'automated_passed','automated_failed','manual_passed','manual_failed','not_executed'}
COURSE_006_PRECONDITIONS={'attack_course':'course-b','attack_owner':'student-a',
    'proposal_status_before':'pending','revoked_course':'course-b'}

def correct_course_006(properties):
    return all(properties.get(key)==value for key,value in COURSE_006_PRECONDITIONS.items())

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def case_hash(case):return hashlib.sha256(json.dumps(case,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def node_id(case):return 'backend/'+case.attrib['classname'].replace('.','/')+'.py::'+case.attrib['name']

def junit(path):
    tree=ET.parse(path);suites=list(tree.getroot().iter('testsuite'))
    result={}
    for case in tree.getroot().iter('testcase'):
        node=node_id(case)
        if node in result:raise ValueError('Duplicate executed node '+node)
        state='automated_failed' if case.find('failure') is not None or case.find('error') is not None else 'not_executed' if case.find('skipped') is not None else 'automated_passed'
        result[node]={'status':state,'duration_seconds':float(case.attrib['time']),
            'timestamp':suites[0].attrib['timestamp'],
            'properties':{p.attrib['name']:p.attrib.get('value','') for p in case.findall('./properties/property')}}
    return result

def safe_path(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('Evidence missing or outside repository: '+name)
    return path

def validate_manifest(manifest,root=ROOT):
    planned=json.loads((root/'data/evaluation/security_cases.yaml').read_text(encoding='utf-8'))['cases']
    by_id={c['case_id']:c for c in planned}
    rows=manifest['cases'];ids=[r['case_id'] for r in rows]
    if len(ids)!=164 or len(set(ids))!=164 or set(ids)!=set(by_id):raise ValueError('Exactly the original 164 unique case IDs required')
    for filename,sha in manifest['datasets'].items():
        path=safe_path(root,filename)
        normalized=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if normalized!=manifest['dataset_lf_sha256'][filename]:raise ValueError('Frozen dataset changed: '+filename)
    commands=json.loads((root/'docs/experiments/wave3-command-results.json').read_text(encoding='utf-8'))['commands']
    runs=[{k:r[k] for k in ('command','cwd','start','end','exit_code')} for r in commands]
    cached={}
    for row in rows:
        if row['case_sha256']!=case_hash(by_id[row['case_id']]):raise ValueError('Planned case drift')
        if row['operation']!=by_id[row['case_id']]['input']['operation']:raise ValueError('Operation differs from planned case')
        if row['status'] not in STATUSES:raise ValueError('Invalid execution status')
        if row['status']=='not_executed':
            if not row.get('reason') or not row.get('blocker'):raise ValueError('Unexecuted sensitive case requires concrete blocker/reason')
            if row.get('executed_at') is not None:raise ValueError('Unexecuted case cannot fabricate a timestamp')
            continue
        if not row.get('evidence') or not row.get('executed_at'):raise ValueError('Execution evidence and timestamp required')
        if row['status'].startswith('manual_'):raise ValueError('This Gate has no signed manual attack verdicts')
        for evidence in row['evidence']:
            path=safe_path(root,evidence['path'])
            if digest(path)!=evidence['sha256']:raise ValueError('Evidence digest mismatch')
            if str(path) not in cached:cached[str(path)]=junit(path)
            actual=cached[str(path)].get(evidence['node'])
            if not actual or actual['status']!=row['status']:raise ValueError('Case not executed with claimed result')
            if by_id[row['case_id']]['input']['attack_category']=='small_sample':
                wanted='backend/tests/integration/test_wave3_analytics_vectors_postgres.py::test_vector_through_official_router_sql_postgres[analytics-'+row['case_id'].removeprefix('sec-small-sample-')+']'
                if evidence['node']!=wanted:raise ValueError('Wrong original SQL vector operation')
            elif actual['properties'].get('case_id')!=row['case_id']:raise ValueError('Evidence belongs to another attack case')
            if row['case_id']=='sec-cross-course-006' and not correct_course_006(actual['properties']):
                raise ValueError('Planned course/proposal preconditions not executed')
            if actual['timestamp']!=row['executed_at'] or actual['duration_seconds']!=evidence['duration_seconds']:raise ValueError('Timing differs from executed node')
            run=row['run']
            if run not in runs:raise ValueError('Command not present in actual execution ledger')
            xml_arguments=[arg.split('=',1)[1].replace('\\','/') for arg in run['command'] if arg.startswith('--junitxml=')]
            if not any(arg.endswith('/'+path.name) for arg in xml_arguments):raise ValueError('Command did not produce this report')
            if not run.get('command') or not run.get('cwd') or not run.get('start') or not run.get('end'):raise ValueError('Actual command metadata required')
            if run['exit_code']!=0 and row['status']=='automated_passed':raise ValueError('Passing claim cannot use a failed command')
    return dict(Counter(r['status'] for r in rows))

def build(root=ROOT):
    cases=json.loads((root/'data/evaluation/security_cases.yaml').read_text(encoding='utf-8'))['cases']
    files={'local':('concrete-local.xml','G9-local-final'),'pg':('postgres-cases.xml','G9-PG-parameters-final'),
           'container':('container-attacks.xml','G9-container-attacks-confirmed')}
    commands=json.loads((root/'docs/experiments/wave3-command-results.json').read_text(encoding='utf-8'))['commands']
    if (root/'docs/experiments/wave3-evidence/concrete-local-repair.xml').exists():
        files['local']=('concrete-local-repair.xml','G10-repair-case-execution-confirmed')
    if (root/'docs/experiments/wave3-evidence/backend-after-review.xml').exists() and any(
        r['phase']=='G10-post-review-backend' and r['exit_code']==0 for r in commands):
        files={key:('backend-after-review.xml','G10-post-review-backend') for key in files}
    reports={key:junit(root/'docs/experiments/wave3-evidence'/file) for key,(file,_) in files.items()}
    rows=[]
    for case in cases:
        cid=case['case_id'];category=case['input']['attack_category']
        tier='pg' if category=='small_sample' or cid in {'sec-cross-role-002','sec-cross-role-008','sec-deletion-recovery-005'} else 'container' if cid in {'sec-executor-abuse-006','sec-executor-abuse-007','sec-executor-abuse-008'} else 'local'
        if category=='small_sample':
            vector='analytics-'+cid.removeprefix('sec-small-sample-')
            wanted='test_vector_through_official_router_sql_postgres['+vector+']'
        else:wanted=cid+']'
        matches=[(node,r) for node,r in reports[tier].items() if node.endswith(wanted)]
        if len(matches)!=1:raise ValueError('No unique actual operation for '+cid)
        node,actual=matches[0];file,phase=files[tier]
        record=next((r for r in reversed(commands) if r['phase']==phase),None)
        if record is None:raise ValueError('Actual command missing: '+phase)
        row={'case_id':cid,'case_sha256':case_hash(case),'operation':case['input']['operation'],
            'planned_tier':case['input']['execution_tier'],'actual_tier':tier,
            'sensitivity':'high' if category in {'idor','cross_student','cross_course','cross_role','memory_leakage','deletion_recovery','share_bypass','small_sample'} else 'medium',
            'status':actual['status'],'executed_at':actual['timestamp'],
            'mapping_basis':'Exact case-ID parameter executes the named operation.' if category!='small_sample' else 'Original vector-ID parameter executes all seeded facts through official SQL Router.',
            'boundary':'Synthetic SQL PostgreSQL authority; Mock provider/index where applicable.' if tier=='pg' else 'Actual hardened SDK 1.2.0 container, fixed limits, synthetic source only.' if tier=='container' else 'Real authorization/deletion/model-input code; synthetic in-memory stores/index and deterministic Mock provider; not physical external storage proof.',
            'run':{k:record[k] for k in ('command','cwd','start','end','exit_code')},
            'evidence':[{'path':'docs/experiments/wave3-evidence/'+file,'sha256':digest(root/'docs/experiments/wave3-evidence'/file),'node':node,'duration_seconds':actual['duration_seconds']}]}
        if cid=='sec-cross-course-006' and not correct_course_006(actual['properties']):
            row.update(status='not_executed',executed_at=None,
                reason='Independent review confirmed that the executed node revoked student-b in course-a and accessed an already accepted course-a proposal. The planned operation requires student-a with a pending course-b proposal after course-b enrollment revocation. The wrong-scenario observation cannot prove this planned attack passed; product implementation is paused pending user authorization.',
                blocker='WG-CASE-CROSS-COURSE-006',observation=row['evidence'])
            row['evidence']=[]
        elif cid=='sec-sensitive-logging-008':
            row.update(status='not_executed',executed_at=None,
                reason='The actual observation confirms client-controlled X-Request-ID is echoed. The planned case does not define an admissible correlation format or a denial criterion. No claim of correlation-header sanitization is made; an explicit API/security decision is needed before calling this attack passed.',
                blocker='WG-CORRELATION-POLICY',observation=row['evidence'])
            row['evidence']=[]
        rows.append(row)
    result={'version':'wave3-gate-executed-v1','data':'synthetic only; no real models or learners',
        'datasets':{p:digest(root/p) for p in ['data/evaluation/security_cases.yaml','data/evaluation/analytics_vectors.yaml','data/evaluation/diagnosis_cases.yaml']},
        'dataset_lf_sha256':{p:hashlib.sha256((root/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in ['data/evaluation/security_cases.yaml','data/evaluation/analytics_vectors.yaml','data/evaluation/diagnosis_cases.yaml']},
        'external_adapter_gaps':[
            {'id':'WG-EXTERNAL-ERASURE','reason':'Retrieval/cache/model-reference adapters are in-memory. Installed pgvector is not an implemented persistent vector adapter; physical external erasure, late external writers and cache invalidation are not proven. Require ADR and authorized adapter scope before production.'}
        ],'cases':rows}
    validate_manifest(result,root)
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',default='data/evaluation/security_execution_manifest.json');parser.add_argument('--build',action='store_true');args=parser.parse_args()
    path=ROOT/args.manifest
    if args.build:path.write_text(json.dumps(build(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    counts=validate_manifest(json.loads(path.read_text(encoding='utf-8')))
    print(json.dumps({'case_count':164,'statuses':counts,'teaching_annotations':'unchanged draft'},ensure_ascii=True))

if __name__=='__main__':main()
