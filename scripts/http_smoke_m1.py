"""Actual loopback HTTP smoke; never calls GitHub or a model provider.
Creates temporary credentials/data; shuts down its server before returning.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
def main() -> None:
    Path(os.getenv('TF_REPORT_DIR', str(ROOT/'reports'/'local'))).mkdir(parents=True, exist_ok=True)
    checks=[]
    result={'mode':'independent_sqlite_simulator','real_llm_called':False,'real_github_pr_created':False,'checks':checks}
    with tempfile.TemporaryDirectory(prefix='traceforge-http-') as tmp:
        data=Path(tmp)
        developer=secrets.token_urlsafe(36); reviewer=secrets.token_urlsafe(36)
        env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'TF_DATABASE_URL':'sqlite:///'+str(data/'db.sqlite'),
             'TF_DATA_DIR':str(data),'TF_DEVELOPER_TOKEN':developer,'TF_REVIEWER_TOKEN':reviewer,
             'TF_WEBHOOK_SECRET':secrets.token_urlsafe(36)}
        subprocess.run([sys.executable,'-m','traceforge.cli','init'],cwd=ROOT,env=env,check=True,capture_output=True,timeout=30)
        checks.append('alembic_upgrade_and_fixture_seed')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        with (data/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','traceforge.api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=15,trust_env=False) as c:
                    for _ in range(100):
                        try:
                            if c.get('/healthz').status_code==200: break
                        except httpx.TransportError: pass
                        if server.poll() is not None: raise RuntimeError('API process stopped')
                        time.sleep(.1)
                    else: raise RuntimeError('API startup timeout')
                    checks.append('real_tcp_health')
                    page=c.get('/workbench'); assert page.status_code==200 and 'TraceForge' in page.text
                    assert c.get('/workbench-assets/app.mjs').status_code==200
                    checks.append('served_workbench_html_and_javascript')
                    assert c.get('/api/v1/projects').status_code==401
                    h={'Authorization':'Bearer '+reviewer}
                    dh={'Authorization':'Bearer '+developer}
                    projects=c.get('/api/v1/projects',headers=h).json()['items']; assert len(projects)==3
                    project=next(p for p in projects if p['fixture_id']=='pagination')
                    checks.append('authentication_and_projects')
                    body={'project_id':project['id'],'objective':'删除最后一页最后一条记录后，分页应回退到最后一个有效页面。','runtime':'fixture'}
                    rh={**h,'Idempotency-Key':'smoke-'+secrets.token_hex(12)}
                    run=c.post('/api/v1/runs',json=body,headers=rh); assert run.status_code==201,run.text
                    rid=run.json()['id']
                    assert c.post('/api/v1/runs',json=body,headers=rh).json()['id']==rid
                    checks.append('create_run_and_idempotent_replay')
                    subprocess.run([sys.executable,'-m','traceforge.worker','--drain'],cwd=ROOT,env=env,capture_output=True,check=True,timeout=30)
                    detail=c.get('/api/v1/runs/'+rid,headers=h).json(); assert detail['status']=='WAITING_APPROVAL',detail
                    checks.append('separate_worker_process_reproduce_patch_verify')
                    a=detail['approval']; decision={k:a[k] for k in ['base_commit','patch_hash','validation_digest']}; decision['decision']='APPROVED'; decision['delivery_kind']='SIMULATED_PR'
                    route=f'/api/v1/approvals/{a["id"]}/decision'
                    delivery=f'/api/v1/runs/{rid}/deliveries/simulated'; payload={'approval_id':a['id']}
                    assert c.post(delivery,json=payload,headers=h).status_code==403
                    assert c.post(route,json=decision,headers=dh).status_code==403
                    checks.append('unapproved_delivery_and_developer_approval_blocked')
                    assert c.post(route,json=decision,headers=h).status_code==200
                    first=c.post(delivery,json=payload,headers=h); assert first.status_code==200,first.text
                    assert c.post(delivery,json=payload,headers=h).json()['id']==first.json()['id']
                    checks.append('bound_action_approval_and_idempotent_simulated_delivery')
                    real=c.post(f'/api/v1/runs/{rid}/deliveries/pr',json=payload,headers=h)
                    assert real.status_code==503 and real.json()['error']['code']=='LIVE_DELIVERY_DISABLED'
                    checks.append('real_github_delivery_fails_closed')
                    audit=c.get(f'/api/v1/runs/{rid}/evidence',headers=h)
                    assert audit.status_code==200 and audit.json()['integrity_and_fixture_policy_passed'] is True
                    checks.append('evidence_integrity_and_semantic_audit')
                    bundle=c.get(f'/api/v1/runs/{rid}/evidence/export',headers=h)
                    assert bundle.status_code==200
                    path=data/'bundle.json';path.write_bytes(bundle.content)
                    offline=subprocess.run([sys.executable,'-m','traceforge.cli','verify-bundle',str(path)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=15)
                    assert offline.returncode==0,offline.stdout+offline.stderr
                    assert json.loads(offline.stdout)['authenticity_proven'] is False
                    checks.append('http_export_and_offline_integrity_cli')
                    op=first.json()
                    reconciled=c.post(f'/api/v1/runs/{rid}/operations/{op["id"]}/reconcile',headers=h)
                    assert reconciled.status_code==200 and reconciled.json()['id']==op['id']
                    checks.append('read_only_operation_reconciliation')
                    events=c.get(f'/api/v1/runs/{rid}/events?stream=false',headers=h).json()['items']
                    assert [e['sequence'] for e in events]==list(range(1,len(events)+1))
                    sse=c.get(f'/api/v1/runs/{rid}/events',headers={**h,'Last-Event-ID':str(len(events)-1)})
                    assert sse.status_code==200 and f'id: {len(events)}\n' in sse.text
                    checks.append('sse_last_event_id_resume')
                    export=Path(os.getenv('TF_EXAMPLE_DIR', str(ROOT/'examples'/'local-executed-fixture'))); export.mkdir(parents=True,exist_ok=True)
                    artifacts=c.get(f'/api/v1/runs/{rid}/artifacts',headers=h).json()['items']
                    for item in artifacts:
                        content=c.get(f'/api/v1/runs/{rid}/artifacts/{item["id"]}',headers=h).content
                        ext='diff' if item['kind']=='patch' else 'json'
                        (export/f'{item["kind"]}.{ext}').write_bytes(content)
                    (export/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
                    (export/'README.md').write_text('# 实际运行样例\n\n来源：本项目预先审阅的分页缺陷 fixture。补丁为确定性已知补丁，不是 LLM 生成。修改前、修改后均实际运行四项 unittest；运行了独立 Git checkout 和 git apply。交付文件来自独立 SQLite 模拟端，不是真实 PR。事件内时间为本次实际运行时间。\n')
                    result.update({'passed':True,'check_count':len(checks),'event_count':len(events),'artifact_count':len(artifacts),'final_state':c.get('/api/v1/runs/'+rid,headers=h).json()['status']})
            finally:
                server.terminate()
                try: server.wait(timeout=5)
                except subprocess.TimeoutExpired: server.kill();server.wait()
    (Path(os.getenv('TF_REPORT_DIR', str(ROOT/'reports'/'local')))/'http-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
