"""Execution claims must be joined to per-node results, never file-level green."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[3]

def mapper():
    spec=importlib.util.spec_from_file_location('wave3_mapping',ROOT/'data/evaluation/map_security_execution.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_exact_164_execution_claims_are_verified_against_evidence():
    module=mapper()
    manifest=json.loads((ROOT/'data/evaluation/security_execution_manifest.json').read_text(encoding='utf-8'))
    module.validate_manifest(manifest,ROOT)
    assert len(manifest['cases'])==164

def test_reviewed_wrong_scenario_is_not_reported_as_attack_passed(monkeypatch):
    module=mapper()
    original=module.junit
    def wrong_scenario(path):
        report=original(path)
        for node,result in report.items():
            if node.endswith('[sec-cross-course-006]'):
                result['properties'].update(attack_course='course-a',attack_owner='student-b',
                    proposal_status_before='accepted',revoked_course='course-a')
        return report
    monkeypatch.setattr(module,'junit',wrong_scenario)
    manifest=module.build()
    row=next(row for row in manifest['cases'] if row['case_id']=='sec-cross-course-006')
    assert row['status']=='not_executed'
    assert row['blocker']=='WG-CASE-CROSS-COURSE-006'

@pytest.mark.parametrize('mutation',['missing','duplicate','status','evidence','collected','hash','wrong_case','operation','command'])
def test_mapping_rejects_unverifiable_execution_claims(mutation):
    module=mapper()
    manifest=json.loads((ROOT/'data/evaluation/security_execution_manifest.json').read_text(encoding='utf-8'))
    changed=copy.deepcopy(manifest)
    passed=next(c for c in changed['cases'] if c['status']=='automated_passed')
    if mutation=='missing':changed['cases'].pop()
    elif mutation=='duplicate':changed['cases'].append(copy.deepcopy(passed))
    elif mutation=='status':passed['status']='collected'
    elif mutation=='evidence':passed['evidence'][0]['path']='nonexistent-wave3-evidence.xml'
    elif mutation=='collected':passed['evidence'][0]['node']='collected-but-never-run'
    elif mutation=='hash':passed['evidence'][0]['sha256']='0'*64
    elif mutation=='wrong_case':
        other=next(c for c in changed['cases'] if c['status']=='automated_passed' and c['case_id']!=passed['case_id'] and c['evidence'][0]['path']==passed['evidence'][0]['path'])
        for field in ('evidence','executed_at','run'):passed[field]=copy.deepcopy(other[field])
    elif mutation=='operation':passed['operation']='different operation never executed'
    else:passed['run']['command']=['never-executed-command']
    with pytest.raises(ValueError):module.validate_manifest(changed,ROOT)
