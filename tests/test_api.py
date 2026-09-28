import hashlib
import hmac
import json
import uuid
import pytest
from conftest import DEV,SECRET


def test_health_public(client): assert client.get("/healthz").json()["mode"]=="trusted_fixture_only"

def test_auth_required(client): assert client.get("/api/v1/runs").status_code==401

def test_invalid_token(client): assert client.get("/api/v1/runs",headers={"Authorization":"Bearer wrong"}).status_code==401

def test_meta_is_honest(client,headers):
    meta=client.get("/api/v1/meta",headers=headers).json()
    assert meta["real_llm_connected"] is False and meta["real_github_connected"] is False

def test_create_contract(client,headers):
    project=client.get("/api/v1/projects",headers=headers).json()["items"][0]
    request={"project_id":project["id"],"objective":"Repair reviewed fixture"}
    h={**headers,"Idempotency-Key":"api-creation-key"}
    a=client.post("/api/v1/runs",headers=h,json=request)
    assert a.status_code==201
    assert a.json()["id"]==client.post("/api/v1/runs",headers=h,json=request).json()["id"]
    assert client.post("/api/v1/runs",headers=h,json={**request,"runtime":"openhands"}).status_code==422
    assert client.post("/api/v1/runs",headers=h,json={**request,"shell":"rm -rf /"}).status_code==422

def test_live_delivery_fails_explicitly(client,headers,complete):
    run,a,_=complete()
    response=client.post(f"/api/v1/runs/{run.id}/deliveries/pr",headers=headers,json={"approval_id":a.id})
    assert response.status_code==503
    assert response.json()["error"]["code"]=="LIVE_DELIVERY_DISABLED"

def test_developer_api_approval_forbidden(client,complete):
    _,a,r=complete()
    response=client.post(f"/api/v1/approvals/{a.id}/decision",headers={"Authorization":"Bearer "+DEV},json=r.model_dump())
    assert response.status_code==403

def test_complete_api_local_receipt(client,headers,complete):
    run,a,r=complete()
    assert client.get(f"/api/v1/runs/{run.id}/patch",headers=headers).json()["diff"].startswith("diff --git")
    assert client.post(f"/api/v1/approvals/{a.id}/decision",headers=headers,json=r.model_dump()).status_code==200
    delivery=client.post(f"/api/v1/runs/{run.id}/deliveries/local",headers=headers,json={"approval_id":a.id})
    assert delivery.status_code==200
    assert client.get(f"/api/v1/runs/{run.id}",headers=headers).json()["status"]=="DELIVERED_LOCAL"

def test_artifact_is_scoped_to_run(client,headers,complete):
    one,_,_=complete();two,_,_=complete("empty-mean")
    artifact_id=one.data["patch_artifact_id"]
    assert client.get(f"/api/v1/runs/{two.id}/artifacts/{artifact_id}",headers=headers).status_code==404

def test_sse_resume_uses_last_event_id(client,headers,complete):
    run,_,_=complete()
    response=client.get(f"/api/v1/runs/{run.id}/events",headers={**headers,"Last-Event-ID":"5"})
    assert response.status_code==200
    assert "text/event-stream" in response.headers["content-type"]
    ids=[int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids and min(ids)==6 and ids==sorted(set(ids))

def test_sse_cursor_validation(client,headers,new_run):
    run=new_run()
    assert client.get(f"/api/v1/runs/{run.id}/events",headers={**headers,"Last-Event-ID":"bad"}).status_code==400

def test_event_polling(client,headers,complete):
    run,_,_=complete();response=client.get(f"/api/v1/runs/{run.id}/events?stream=false&after_seq=2",headers=headers)
    assert response.json()["items"][0]["sequence"]==3

def signed(body,delivery="test-delivery-id"):
    return {"X-Hub-Signature-256":"sha256="+hmac.new(SECRET.encode(),body,hashlib.sha256).hexdigest(),
            "X-GitHub-Delivery":delivery,"X-GitHub-Event":"ping","Content-Type":"application/json"}

def test_webhook_verified_and_deduped(client):
    body=json.dumps({"zen":"中文 payload"},ensure_ascii=False).encode();h=signed(body)
    a=client.post("/api/v1/webhooks/github",content=body,headers=h)
    b=client.post("/api/v1/webhooks/github",content=body,headers=h)
    assert a.status_code==200 and a.json()["duplicate"] is False
    assert b.json()["duplicate"] is True and b.json()["queued"] is False

def test_webhook_replay_different_payload_denied(client):
    first=b'{"a":1}';second=b'{"a":2}'
    client.post("/api/v1/webhooks/github",content=first,headers=signed(first))
    assert client.post("/api/v1/webhooks/github",content=second,headers=signed(second)).status_code==409

def test_bad_signature_rejected_before_json_parsing(client):
    body=b'not json';h=signed(body);h["X-Hub-Signature-256"]="sha256=wrong"
    assert client.post("/api/v1/webhooks/github",content=body,headers=h).status_code==403

def test_signed_invalid_json(client):
    body=b'not json'
    assert client.post("/api/v1/webhooks/github",content=body,headers=signed(body)).status_code==400

def test_webhook_body_limit(client):
    body=b'x'*262145
    assert client.post("/api/v1/webhooks/github",content=body,headers=signed(body)).status_code==413

def test_openapi_exposes_contracts(client):
    schema=client.get("/openapi.json").json()
    assert "ApprovalDecision" in schema["components"]["schemas"]
    assert "/api/v1/runs/{run_id}/events" in schema["paths"]

def test_no_token_in_error_body(client):
    response=client.get("/api/v1/runs",headers={"Authorization":"Bearer a-super-secret"})
    assert "a-super-secret" not in response.text
