"""Concrete planned operations; case IDs are the executed pytest parameters.

Production authorization/deletion services are real. Only the documented
local tier's persistence/provider/index are synthetic in-memory adapters.
Small-sample cases are executed separately through official SQL routes.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.memories.models import LearningMemoryStatus
from app.model_gateway.base import ProviderTimeout
from app.model_gateway.mock import DeterministicMockProvider
from .security_support import (build_harness, STUDENT_A, STUDENT_B, TEACHER,
    OTHER_TEACHER, COURSE_A, COURSE_B, public_denial, PRIVATE_B)
from . import test_prompt_injection as prompt
from . import test_cross_course_memory as memory
from . import test_security_repairs as repairs
from . import test_idor as idor

ROOT=Path(__file__).resolve().parents[3]
CASES=json.loads((ROOT/'data/evaluation/security_cases.yaml').read_text(encoding='utf-8'))['cases']
# These operations have separate real-PG/container execution nodes.
SEPARATE={'sec-cross-role-002','sec-cross-role-008','sec-deletion-recovery-005',
          'sec-executor-abuse-006','sec-executor-abuse-007','sec-executor-abuse-008'}
LOCAL=[c for c in CASES if c['input']['attack_category']!='small_sample' and c['case_id'] not in SEPARATE]

def grant(h,actor=STUDENT_A,diagnosis='diagnosis-a'):
    return h.state.memory_service.create_share_grant(actor,diagnosis,TEACHER.user_id,
        purpose='synthetic-review',request_id='seed-grant',idempotency_key='seed-grant')

@pytest.mark.parametrize('case',LOCAL,ids=lambda c:c['case_id'])
def test_planned_operation(case,caplog,monkeypatch,record_property):
    record_property('case_id',case['case_id'])
    record_property('operation',case['input']['operation'])
    category=case['input']['attack_category'];n=int(case['case_id'].rsplit('-',1)[1])
    if category=='prompt_injection':
        prompt.test_untrusted_channels_cannot_rewrite_evidence_roles_or_memory(case['input']['channel'],case['input']['payload'],caplog,monkeypatch)
        return
    h=build_harness(pending_other_course=category=='cross_course' and n==6)
    if category in {'idor','cross_student'}:
        p=h.proposals['b'].proposal_id;m=h.memories['b'].memory_id
        g=grant(h,STUDENT_B,'diagnosis-b')
        d=h.state.deletion_service.delete_memory(STUDENT_B,m,request_id='seed-delete',idempotency_key='seed-delete')
        operations=[('GET','/submissions/submission-b',None),('GET','/submissions/submission-b/execution-result',None),
            ('GET','/submissions/submission-b/diagnosis',None),('POST','/diagnoses/diagnosis-b/hints/next',{'reason':'synthetic'}),
            ('POST',f'/memory-proposals/{p}/accept',None),('PATCH',f'/memories/{m}',{'content':'synthetic'}),
            ('DELETE',f'/memories/{m}',None),('GET',f'/memory-deletions/{d.deletion_id}',None)] if category=='idor' else [
            ('POST','/diagnoses/diagnosis-b/explanation-check',{'explanation':'synthetic'}),('POST',f'/memory-proposals/{p}/reject',None),
            ('PATCH',f'/memory-proposals/{p}',{'content':'synthetic'}),('DELETE',f'/share-grants/{g.grant_id}',None),
            ('POST',f'/memory-deletions/{d.deletion_id}/retry',None),('POST','/diagnoses/diagnosis-b/share-grants',{'grantee_user_id':TEACHER.user_id,'purpose':'synthetic'})]
        if category=='cross_student' and n==7:memory.test_index_cannot_expand_owner_course_or_pending_proposal_scope(h);return
        if category=='cross_student' and n==8:
            r=h.request('PATCH',f'/memories/{h.memories["a"].memory_id}',body={'content':'synthetic','owner_user_id':STUDENT_B.user_id})
            assert r.status_code==422;return
        method,path,body=operations[n-1];public_denial(h.request(method,path,body=body))
        assert not h.provider.diagnosis_requests and not h.provider.hint_requests and not h.provider.explanation_requests
    elif category=='cross_course':
        if n==1:public_denial(h.request('GET','/courses/course-b/exercises',actor=STUDENT_B))
        elif n==2:public_denial(h.request('POST','/exercises/exercise-b/submissions',actor=STUDENT_B,body={'source_files':[{'path':'main.cj','content':'main() {}'}],'entrypoint':'main.cj'}))
        elif n in (3,4):
            h.state.memory_index.inject_search_results(h.memories['a-other'].index_document_id)
            assert h.state.memory_service.search_memories(STUDENT_A,COURSE_A,h.memories['a-other'].content,purpose='learning_support')==()
        elif n==5:public_denial(h.request('POST','/diagnoses/diagnosis-a-other/share-grants',body={'grantee_user_id':TEACHER.user_id,'purpose':'synthetic'}))
        elif n==6:
            proposal=h.state.memory_repository.get_proposal(h.proposals['a-other'].proposal_id)
            assert proposal.course_id==COURSE_B and proposal.owner_user_id==STUDENT_A.user_id
            assert proposal.status.value=='pending' and proposal.accepted_memory_id is None
            assert h.state.memory_repository.get_memory_for_proposal(proposal.proposal_id) is None
            record_property('attack_course',proposal.course_id)
            record_property('attack_owner',proposal.owner_user_id)
            record_property('proposal_status_before',proposal.status.value)
            assert proposal.proposal_id in {p['proposal_id'] for p in h.request('GET','/me/memory-proposals?course_id=course-b').json()}
            h.revoke_enrollment(STUDENT_A,COURSE_B)
            record_property('revoked_course',COURSE_B)
            response=h.request('POST',f'/memory-proposals/{proposal.proposal_id}/accept',actor=STUDENT_A)
            public_denial(response)
            assert proposal.content not in response.text+caplog.text
            public_denial(h.request('GET','/me/memory-proposals?course_id=course-b',actor=STUDENT_A))
            after=h.state.memory_repository.get_proposal(proposal.proposal_id)
            assert after.status.value=='pending' and after.accepted_memory_id is None
            assert h.state.memory_repository.get_memory_for_proposal(proposal.proposal_id) is None
            assert not h.provider.diagnosis_requests and not h.provider.hint_requests and not h.provider.explanation_requests
        elif n==7:
            h.revoke_enrollment(STUDENT_A,COURSE_A);public_denial(h.request('GET','/submissions/submission-a'))
        else:assert h.request('PATCH',f'/memories/{h.memories["a"].memory_id}',body={'content':'synthetic','course_id':COURSE_B}).status_code==422
    elif category=='cross_role':
        p=h.proposals['pending'].proposal_id;m=h.memories['a'].memory_id
        method,path,body={1:('GET','/teacher/courses/course-a/concepts',None),3:('GET','/me/memories?course_id=course-a',None),
            4:('POST',f'/memory-proposals/{p}/accept',None),5:('POST',f'/memory-proposals/{p}/reject',None),
            6:('PATCH',f'/memories/{m}',{'content':'synthetic'}),7:('DELETE',f'/memories/{m}',None)}[n]
        public_denial(h.request(method,path,body=body,actor=STUDENT_A if n==1 else TEACHER))
    elif category=='memory_leakage':
        if n==1:public_denial(h.request('GET','/me/memory-proposals?course_id=course-a',actor=TEACHER))
        elif n==8:prompt.test_deleted_memory_original_text_cannot_reenter_model_context()
        elif n==7:
            h=build_harness(provider=DeterministicMockProvider(diagnoses=[prompt.model_output()]))
            h.state.memory_index.inject_search_results(h.memories['b'].index_document_id)
            prompt.submitted(h)
            assert h.provider.diagnosis_requests and PRIVATE_B not in h.provider.diagnosis_requests[0].model_dump_json()
        else:
            allowed=h.memories['a']
            if n==3:
                expired=replace(allowed,expires_at=allowed.created_at-timedelta(seconds=1))
                h.state.memory_repository.save_memory(expired)
            if n==4:h.state.memory_service.correct_memory(STUDENT_A,allowed.memory_id,'synthetic replacement',request_id='correct',idempotency_key='correct')
            ids=[allowed.index_document_id] if n in (3,4) else ['unknown'] if n in (2,6) else [allowed.index_document_id]*2
            h.state.memory_index.inject_search_results(*ids)
            query=h.proposals['pending'].content if n==2 else allowed.content
            result=h.state.memory_service.search_memories(STUDENT_A,COURSE_A,query,purpose='learning_support')
            assert result==((allowed,) if n==5 else ())
    elif category=='deletion_recovery':
        if n in (1,2,3,4):memory.test_delete_erases_lineage_and_original_query_even_when_cleanup_fails(h,{1:'none',2:'index_delete',3:'reverse_verification',4:'index_delete'}[n])
        elif n==6:memory.test_late_upsert_must_not_restore_physical_original_text(h)
        elif n==7:
            p=h.proposals['pending'].proposal_id
            a=h.request('POST',f'/memory-proposals/{p}/accept',key='original-accept');assert a.status_code==200
            assert h.request('DELETE',f'/memories/{a.json()["memory_id"]}').status_code==202
            repeated=h.request('POST',f'/memory-proposals/{p}/accept',key='original-accept')
            assert repeated.status_code in (200,409)
            assert all(m.content is None for m in h.state.memory_repository.memory_lineage(a.json()['logical_memory_id']))
        else:
            g=grant(h);h.state.memory_index.fail_next_deletes(1)
            h.state.deletion_service.delete_memory(STUDENT_A,h.memories['a'].memory_id,request_id='delete',idempotency_key='delete')
            public_denial(h.request('GET',f'/share-grants/{g.grant_id}/diagnosis-summary',actor=TEACHER))
    elif category=='share_bypass':
        g=grant(h);path=f'/share-grants/{g.grant_id}/diagnosis-summary'
        if n==1:public_denial(h.request('GET',path,actor=OTHER_TEACHER))
        elif n==2:
            legitimate=h.request('GET',path+'?diagnosis_id=diagnosis-b',actor=TEACHER)
            assert legitimate.status_code==200 and legitimate.json()['diagnosis_id']=='diagnosis-a' and PRIVATE_B not in legitimate.text
        elif n==3:public_denial(h.request('GET',f'/me/memories?course_id=course-a&share_grant_id={g.grant_id}',actor=TEACHER))
        elif n==4:
            assert h.request('DELETE',f'/share-grants/{g.grant_id}').status_code==200;public_denial(h.request('GET',path,actor=TEACHER))
        elif n==5:
            h.state.memory_repository.save_grant(replace(g,expires_at=g.created_at-timedelta(seconds=1)))
            public_denial(h.request('GET',path,actor=TEACHER))
        elif n==6:
            h.courses._courses[COURSE_A]=replace(h.courses.get(COURSE_A),owner_teacher_id=OTHER_TEACHER.user_id)
            public_denial(h.request('GET',path,actor=TEACHER))
        elif n==7:assert h.request('POST','/diagnoses/diagnosis-a/share-grants',body={'grantee_user_id':TEACHER.user_id,'purpose':'synthetic','resource_type':'learning_memory'}).status_code==422
        else:public_denial(h.request('POST','/diagnoses/diagnosis-b/share-grants',body={'grantee_user_id':TEACHER.user_id,'purpose':'synthetic'}))
    elif category=='sensitive_logging':
        secret='SYNTHETIC_PRIVATE_LOG_MARKER'
        if n==1:prompt.test_provider_failure_does_not_log_sensitive_input_or_return_internal_error(caplog)
        elif n in (2,3):
            r=h.request('POST','/exercises/exercise-a/submissions',body={'source_files':[{'path':'../main.cj','content':secret}],'entrypoint':'../main.cj'}) if n==2 else h.request('PATCH',f'/memories/{h.memories["a"].memory_id}',body={'content':{'private':secret}})
            assert r.status_code==422 and secret not in r.text+caplog.text+h.state.memory_audit.serialized_events()
        elif n==4:
            h=build_harness(provider=DeterministicMockProvider(explanations=[ProviderTimeout(secret)]))
            r=h.request('POST','/diagnoses/diagnosis-a/explanation-check',body={'explanation':secret})
            assert r.status_code==200 and secret not in r.text+caplog.text+h.state.memory_audit.serialized_events()
        elif n==5:prompt.test_untrusted_channels_cannot_rewrite_evidence_roles_or_memory('explanation',prompt.PAYLOADS[1],caplog,monkeypatch)
        elif n==6:prompt.test_raw_source_must_not_enter_final_model_request()
        elif n==7:
            old=h.memories['a'];r=h.request('PATCH',f'/memories/{old.memory_id}',body={'content':secret});assert r.status_code==200
            assert old.content not in h.state.memory_audit.serialized_events() and secret not in h.state.memory_audit.serialized_events()
        else:
            r=h.request('GET','/submissions/unknown',request_id=secret)
            # Correlation is currently client-controlled by the public API.
            # Record that exact observation without calling it sanitization.
            assert r.status_code==404 and r.json()['request_id']==secret
            record_property('limitation','client correlation header is reflected; no assertion of header sanitization')
    elif category=='executor_abuse':
        from runner.worker.protocol import RunnerRequest
        value={'protocol_version':'2','submission_id':'synthetic-protocol','source_files':[{'path':'main.cj','content':'main() {}'}],'entrypoint':'main.cj','timeout_ms':2000}
        if n<=3:
            path={1:'../main.cj',2:'/tmp/main.cj',3:'C:/tmp/main.cj'}[n];value.update(source_files=[{'path':path,'content':'main() {}'}],entrypoint=path)
        else:value.update({('image' if n==4 else 'network'):'attacker-controlled'})
        with pytest.raises(ValidationError):RunnerRequest.model_validate(value)
    elif category=='enumeration_idempotency':
        if n in (1,2,3):idor.test_url_id_replacement_matches_unknown_resource_denial(h,STUDENT_B,{1:'submission',2:'memory_correction',3:'grant'}[n])
        elif n==4:idor.test_idempotency_key_is_scoped_to_resource_type(h)
        elif n==5:
            path=f'/memories/{h.memories["a"].memory_id}'
            assert h.request('PATCH',path,body={'content':'synthetic first'},key='same').status_code==200
            assert h.request('PATCH',path,body={'content':'synthetic changed'},key='same').status_code==409
        elif n==6:
            path=f'/memory-proposals/{h.proposals["pending"].proposal_id}/accept';before=len(h.state.memory_repository.all_memories())
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses=list(pool.map(lambda i:h.request('POST',path,key='concurrent',request_id=f'concurrent-{i}'),range(2)))
            assert all(r.status_code==200 for r in responses)
            assert len(h.state.memory_repository.all_memories())==before+1
            assert responses[0].json()['memory_id']==responses[1].json()['memory_id']
        elif n==7:idor.test_disabled_user_cannot_reuse_signed_token(h)
        else:idor.test_logout_revokes_old_token_at_the_server_boundary(h)
    else:raise AssertionError('Unimplemented concrete operation: '+case['case_id'])
