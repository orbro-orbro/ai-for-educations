"""Read-only proof after the dedicated real-browser scenarios have completed."""
import json
from sqlalchemy import create_engine, text
from tests.integration.wave3_support import postgres_url

def main():
    engine=create_engine(postgres_url('wave3_browser'))
    try:
        with engine.connect() as connection:
            queries={
                'authoritative_reviews':"select count(*) from teacher_diagnosis_reviews",
                'review_audits':"select count(*) from audit_events where event_type='teacher_diagnosis_review'",
                'deleted_versions':"select count(*) from learning_memories where status='deleted' and content is null",
                'remaining_private_versions':"select count(*) from learning_memories where content is not null",
                'rejected_proposals':"select count(*) from memory_proposals where status='rejected'",
                'completed_deletions':"select count(*) from memory_deletions where status='deleted'",
                'revoked_logins':"select count(*) from token_revocations",
            }
            counts={name:connection.scalar(text(query)) for name,query in queries.items()}
        assert counts==dict(authoritative_reviews=1,review_audits=1,deleted_versions=2,
            remaining_private_versions=0,rejected_proposals=1,completed_deletions=1,revoked_logins=3),counts
        print(json.dumps({'database':'wave3_browser','synthetic_only':True,'counts':counts}))
    finally:engine.dispose()

if __name__=='__main__':main()
