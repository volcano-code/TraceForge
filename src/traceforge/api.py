from __future__ import annotations
import asyncio
import json
from pathlib import Path
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from . import __version__
from .artifacts import digest
from .config import Settings
from .db import Database
from .domain import ApprovalDecision, DeliveryRequest, DomainError, RunCreate, STOP_STATES
from .fixtures import FIXTURES
from .models import Approval, Artifact, Operation, Project, Run, RunEvent, WebhookReceipt
from .security import authenticate, verify_webhook
from .services import Services
from .release_info import release_info
from .evidence import EvidenceInspector
from .delivery.service import DeliveryService


def row(obj) -> dict:
    return {column.name:getattr(obj,column.name) for column in obj.__table__.columns}


def create_app(settings: Settings | None=None, database: Database | None=None) -> FastAPI:
    settings=settings or Settings();database=database or Database(settings)
    services=Services(settings,database)
    app=FastAPI(title="TraceForge",version=__version__,description="M2-start execution preflight and reviewed-fixture boundary; no live LLM/GitHub integration.")
    app.state.services=services
    app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],
        allow_methods=["GET","POST"],allow_headers=["Authorization","Content-Type","Idempotency-Key","Last-Event-ID"])

    @app.exception_handler(DomainError)
    async def domain_error(_,error: DomainError):
        return JSONResponse(status_code=error.status,content={"error":{"code":error.code,"message":error.message}})
    @app.exception_handler(IntegrityError)
    async def integrity_error(_,error: IntegrityError):
        return JSONResponse(status_code=409,content={"error":{"code":"CONCURRENT_CONFLICT","message":"Conflict: retry with the same idempotency key"}})
    @app.middleware("http")
    async def security_headers(request: Request,call_next):
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Frame-Options"]="DENY"
        if request.url.path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
        return response
    def actor(authorization: str | None=Header(default=None)) -> str:
        return authenticate(authorization,settings.developer_token,settings.reviewer_token)
    def reviewer(role: str=Depends(actor)) -> str:
        if role!="reviewer": raise DomainError("FORBIDDEN","Reviewer role required",403)
        return role
    prefix="/api/v1"
    @app.get("/healthz")
    def health(): return {"status":"ok","version":__version__,"mode":"trusted_fixture_only"}
    @app.get(prefix+"/meta")
    def meta(role: str=Depends(actor)):
        return {"release":release_info(),"version":__version__,"role":role,"runtime":"fixture","real_llm_connected":False,
          "real_github_connected":False,"evidence_audit":True,"recoverable_simulated_delivery":True,"sandbox":"configured reviewed-fixture backend; see execution readiness",
          "execution_backend":settings.execution_backend,"readiness_endpoint":"/api/v1/execution/readiness",
          "workflow":"database-checkpoint foundation; LangGraph adapter planned",
          "fixtures":[{"id":f.id,"title":f.title,"objective":f.objective} for f in FIXTURES.values()]}
    @app.get(prefix+"/execution/readiness")
    def execution_readiness(probe_docker: bool=False,_: str=Depends(actor)):
        from .execution.readiness import readiness_report
        return readiness_report(settings,probe_docker=probe_docker)
    @app.get(prefix+"/projects")
    def projects(_: str=Depends(actor)):
        with database.session() as s: return {"items":[row(p) for p in s.scalars(select(Project).order_by(Project.name))]}
    @app.post(prefix+"/runs",status_code=201)
    def create(request: RunCreate,idempotency_key: str=Header(...),_: str=Depends(actor)):
        return row(services.create_run(request,idempotency_key))
    @app.get(prefix+"/runs")
    def runs(limit: int=Query(default=30,ge=1,le=100),offset: int=Query(default=0,ge=0),_: str=Depends(actor)):
        with database.session() as s:
            total=s.scalar(select(func.count()).select_from(Run))
            rows=s.scalars(select(Run).order_by(Run.created_at.desc(),Run.id.desc()).limit(limit).offset(offset))
            return {"items":[row(r) for r in rows],"total":total}
    @app.get(prefix+"/runs/{run_id}")
    def get(run_id: str,_: str=Depends(actor)):
        with database.session() as s:
            run=services.get_run(s,run_id)
            approval=s.scalar(select(Approval).where(Approval.run_id==run.id))
            operation=s.scalar(select(Operation).where(Operation.run_id==run.id))
            return {**row(run),"approval":row(approval) if approval else None,"operation":row(operation) if operation else None}
    @app.post(prefix+"/runs/{run_id}/cancel")
    def cancel(run_id: str,_: str=Depends(actor)): return row(services.cancel(run_id))
    @app.get(prefix+"/runs/{run_id}/artifacts")
    def artifacts(run_id: str,_: str=Depends(actor)):
        with database.session() as s:
            services.get_run(s,run_id)
            return {"items":[row(a) for a in s.scalars(select(Artifact).where(Artifact.run_id==run_id).order_by(Artifact.created_at,Artifact.kind))]}
    @app.get(prefix+"/runs/{run_id}/artifacts/{artifact_id}")
    def artifact(run_id: str,artifact_id: str,_: str=Depends(actor)):
        with database.session() as s:
            services.get_run(s,run_id);item=s.get(Artifact,artifact_id)
            if not item or item.run_id!=run_id: raise DomainError("NOT_FOUND","Artifact not found",404)
            content=services.store.read(item)
            # Artifacts are served as text, never executable HTML.
            return Response(content,media_type="text/plain",headers={"X-Artifact-SHA256":item.sha256})
    @app.get(prefix+"/runs/{run_id}/patch")
    def patch(run_id: str,_: str=Depends(actor)):
        with database.session() as s:
            run=services.get_run(s,run_id)
            artifact_id=run.data.get("patch_artifact_id")
            item=s.get(Artifact,artifact_id) if artifact_id else None
            if not item: raise DomainError("NOT_FOUND","Patch not ready",404)
            return {"base_commit":run.base_commit,"patch_hash":item.sha256,"diff":services.store.read(item).decode()}
    @app.post(prefix+"/approvals/{approval_id}/decision")
    def decision(approval_id: str,request: ApprovalDecision,role: str=Depends(reviewer)):
        return row(services.decide(approval_id,request,role))
    @app.post(prefix+"/runs/{run_id}/deliveries/local")
    def local_delivery(run_id: str,request: DeliveryRequest,role: str=Depends(reviewer)):
        return row(services.deliver_local(run_id,request.approval_id,role))
    @app.post(prefix+"/runs/{run_id}/deliveries/pr")
    def live_delivery(run_id: str,request: DeliveryRequest,_: str=Depends(reviewer)):
        raise DomainError("LIVE_DELIVERY_DISABLED","GitHub App delivery is not connected. No PR was created.",503)
    @app.get(prefix+"/runs/{run_id}/evidence")
    def evidence_audit(run_id: str,_: str=Depends(actor)):
        with database.session() as s:
            run=services.get_run(s,run_id)
            approval=s.scalar(select(Approval).where(Approval.run_id==run.id))
            return EvidenceInspector(services.store).inspect(s,run,approval)
    @app.get(prefix+"/runs/{run_id}/evidence/export")
    def evidence_export(run_id: str,_: str=Depends(actor)):
        from .artifacts import canonical
        with database.session() as s:
            run=services.get_run(s,run_id)
            approval=s.scalar(select(Approval).where(Approval.run_id==run.id))
            bundle=EvidenceInspector(services.store).export(s,run,approval)
        return Response(canonical(bundle),media_type="application/json",
                        headers={"Content-Disposition":f'attachment; filename="evidence-{run.id}.json"'})
    @app.get(prefix+"/runs/{run_id}/operations")
    def operations(run_id: str,_: str=Depends(actor)):
        with database.session() as s:
            services.get_run(s,run_id)
            return {"items":[row(op) for op in s.scalars(select(Operation).where(Operation.run_id==run_id).order_by(Operation.created_at,Operation.id))]}
    @app.post(prefix+"/runs/{run_id}/deliveries/simulated")
    def simulated_delivery(run_id: str,request: DeliveryRequest,role: str=Depends(reviewer)):
        return row(DeliveryService(services).submit(run_id,request.approval_id,role))
    @app.post(prefix+"/runs/{run_id}/operations/{operation_id}/reconcile")
    def reconcile(run_id: str,operation_id: str,role: str=Depends(reviewer)):
        return row(DeliveryService(services).reconcile(run_id,operation_id,role))
    @app.get(prefix+"/runs/{run_id}/events")
    async def events(request: Request,run_id: str,after_seq: int=Query(default=0,ge=0),stream: bool=True,
                     last_event_id: str | None=Header(default=None),_: str=Depends(actor)):
        if last_event_id is not None:
            try: after_seq=max(after_seq,int(last_event_id))
            except ValueError as e: raise DomainError("BAD_EVENT_CURSOR","Last-Event-ID must be an integer",400) from e
            if int(last_event_id)<0: raise DomainError("BAD_EVENT_CURSOR","Negative cursor",400)
        with database.session() as s: services.get_run(s,run_id)
        def batch(cursor: int):
            with database.session() as s:
                run=services.get_run(s,run_id)
                items=[row(e) for e in s.scalars(select(RunEvent).where(RunEvent.run_id==run_id,RunEvent.sequence>cursor)
                       .order_by(RunEvent.sequence).limit(200))]
                return items,run.status,run.event_seq
        if not stream:
            items,status,seq=batch(after_seq)
            return JSONResponse({"items":items,"status":status,"last_sequence":seq})
        async def generate():
            cursor=after_seq
            yield ": connected\n\n"
            while not await request.is_disconnected():
                items,status,seq=batch(cursor)
                for event in items:
                    cursor=event["sequence"]
                    yield f"id: {cursor}\nevent: run_event\ndata: {json.dumps(event,ensure_ascii=False)}\n\n"
                if status in STOP_STATES and cursor>=seq: break
                if not items:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(0.5)
        return StreamingResponse(generate(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    @app.post(prefix+"/webhooks/github")
    async def webhook(request: Request,x_hub_signature_256: str | None=Header(default=None),
                      x_github_delivery: str=Header(...),x_github_event: str=Header(...)):
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>262144: raise DomainError("BODY_TOO_LARGE","Webhook body exceeds 256 KiB",413)
            chunks.append(chunk)
        body=b"".join(chunks)
        verify_webhook(body,x_hub_signature_256,settings.webhook_secret)
        if not 1<=len(x_github_delivery)<=128 or not 1<=len(x_github_event)<=80:
            raise DomainError("BAD_WEBHOOK_HEADERS","Invalid delivery identifier or event type",400)
        try: payload=json.loads(body)
        except ValueError as e: raise DomainError("INVALID_JSON","Webhook JSON is invalid",400) from e
        if not isinstance(payload,dict): raise DomainError("INVALID_PAYLOAD","Webhook must be an object",400)
        sha=digest(body)
        with database.transaction() as s:
            old=s.get(WebhookReceipt,x_github_delivery)
            if old:
                if old.payload_hash!=sha or old.event_type!=x_github_event:
                    raise DomainError("WEBHOOK_REPLAY_CONFLICT","Delivery ID reused with different content")
                return {"delivery_id":old.delivery_id,"duplicate":True,"queued":False}
            s.add(WebhookReceipt(delivery_id=x_github_delivery,payload_hash=sha,event_type=x_github_event))
        return {"delivery_id":x_github_delivery,"duplicate":False,"queued":False,
                "note":"Verified receipt only; repository authorization and triggers are not enabled in M0"}
    static=Path(__file__).parent/"static"
    static.mkdir(exist_ok=True)
    app.mount("/workbench-assets",StaticFiles(directory=static),name="workbench-assets")
    @app.get("/",include_in_schema=False)
    def home(): return RedirectResponse("/workbench")
    @app.get("/workbench",include_in_schema=False)
    def workbench(): return FileResponse(static/"index.html")
    return app

app=create_app()
