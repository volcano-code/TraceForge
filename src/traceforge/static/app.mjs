import {createSSEParser,mergeEvents,reviewBinding,canApprove,stopped,phases,labels} from './protocol.mjs';
const $=id=>document.getElementById(id);
let token='',meta=null,projects=[],runs=[],selected=null,run=null,artifactList=[],events=[],pane='patch';
let streamController=null,reviewedBinding='',artifactText='',refreshTimer=null,pollTimer=null,busy=false;
const artifactNames={patch:'Git 补丁',validation:'独立验证报告',reproduction:'修改前复现',regression:'修改后回归',delivery:'本地交付回执',simulated_delivery:'独立模拟端回执'};
function notify(message=''){ $('alert').textContent=message;$('alert').hidden=!message; }
async function api(path,options={}) {
  const response=await fetch('/api/v1'+path,{...options,headers:{Authorization:'Bearer '+token,...(options.body?{'Content-Type':'application/json'}:{}),...options.headers}});
  if(!response.ok){let data={};try{data=await response.json();}catch{}throw new Error(data.error?`${data.error.code} · ${data.error.message}`:`HTTP ${response.status}`);}
  return response.headers.get('content-type')?.includes('application/json')?response.json():response.text();
}
function element(tag,text='',cls=''){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
async function refreshList(){
  const data=await api('/runs?limit=100');runs=data.items;
  $('stat-total').textContent=String(runs.length);$('stat-review').textContent=String(runs.filter(r=>r.status==='WAITING_APPROVAL').length);
  $('stat-done').textContent=String(runs.filter(r=>['DELIVERED_LOCAL','DELIVERED_SIMULATED'].includes(r.status)).length);
  const list=$('run-list');list.replaceChildren();
  for(const item of runs){const b=element('button','','run-item'+(selected===item.id?' selected':''));
    b.append(element('strong',projects.find(p=>p.id===item.project_id)?.name||item.objective));
    const small=element('small');small.append(element('span',item.id.slice(0,8)),element('span',labels[item.status]||item.status));b.append(small);
    b.addEventListener('click',()=>selectRun(item.id).catch(e=>notify(e.message)));list.append(b);}
  if(!runs.length)list.append(element('p','暂时没有任务。先运行一个受控样例。','helper'));
}
function updateObjective(){const project=projects.find(p=>p.id===$('project').value);$('objective').value=meta.fixtures.find(f=>f.id===project?.fixture_id)?.objective||'';}
async function login(value){
  token=value.trim();meta=await api('/meta');projects=(await api('/projects')).items;
  $('project').replaceChildren();$('project-cards').replaceChildren();
  for(const project of projects){const opt=element('option',project.name);opt.value=project.id;$('project').append(opt);
    const card=element('article','','project-card');card.append(element('h3',project.name),element('p',meta.fixtures.find(f=>f.id===project.fixture_id)?.objective||''),element('code','base '+project.base_commit));$('project-cards').append(card);}
  updateObjective();$('login').hidden=true;$('authenticated').hidden=false;$('connection').textContent='已连接 · '+meta.role;$('token').value='';notify();
  await refreshList();const hash=location.hash.slice(1);if(runs.some(r=>r.id===hash))await selectRun(hash);else if(runs.length)await selectRun(runs[0].id);
  clearInterval(pollTimer);pollTimer=setInterval(()=>{if(token)refreshList().catch(e=>notify(e.message));if(selected&&run&&!stopped.has(run.status))refreshSelected().catch(e=>notify(e.message));},5000);
}
function updateReview(){
  const approval=run?.approval;$('review-panel').hidden=!approval;
  if(!approval)return;
  if(run.status!=='WAITING_APPROVAL')$('delivery-kind').value=approval.delivery_kind||'LOCAL_RECEIPT';
  $('delivery-kind').disabled=busy||run.status!=='WAITING_APPROVAL';
  $('review-description').textContent=`Base ${approval.base_commit.slice(0,12)} · Patch ${approval.patch_hash.slice(0,16)} · Report ${approval.validation_digest.slice(0,16)}。批准仅绑定本次版本；当前角色：${meta.role}。`;
  $('approve').disabled=busy||!canApprove(run,meta.role,reviewedBinding,$('delivery-kind').value);
  $('reject').disabled=busy||meta.role!=='reviewer'||run.status!=='WAITING_APPROVAL';
  $('reviewed').disabled=run.status!=='WAITING_APPROVAL';
  $('deliver').hidden=run.status!=='APPROVED';$('deliver').disabled=busy||meta.role!=='reviewer';
  $('deliver').textContent=approval.delivery_kind==='SIMULATED_PR'?'提交到独立模拟端':'生成本地回执';
  $('reconcile').hidden=!['EXECUTING','IN_DOUBT','RECONCILING'].includes(run.operation?.status);
  $('reconcile').disabled=busy||meta.role!=='reviewer';
}
async function selectRun(id){
  streamController?.abort();selected=id;location.hash=id;events=[];reviewedBinding='';$('reviewed').checked=false;$('delivery-kind').value='LOCAL_RECEIPT';$('evidence-status').textContent='证据审计不会重新执行测试';
  await refreshSelected();await refreshList();startStream(id);
}
async function refreshSelected(){
  if(!selected)return;const id=selected;const result=await api('/runs/'+id);if(selected!==id)return;
  if(reviewBinding(result.approval)!==reviewBinding(run?.approval)){reviewedBinding='';$('reviewed').checked=false;}
  run=result;$('empty').hidden=true;$('run-detail').hidden=false;
  $('run-title').textContent=projects.find(p=>p.id===run.project_id)?.name||'验证任务';$('run-status').textContent=labels[run.status]||run.status;
  $('run-id').textContent='#'+run.id.slice(0,8);$('base-sha').textContent='base '+run.base_commit.slice(0,12);
  $('cancel').disabled=busy||['DELIVERED_LOCAL','CANCELLED','REJECTED','FAILED','DELIVERING','DELIVERY_IN_DOUBT','DELIVERED_SIMULATED','DELIVERY_BLOCKED'].includes(run.status);
  if(run.failure_code)notify('任务失败：'+run.failure_code);
  $('phase-track').replaceChildren();const current=['DELIVERING','DELIVERY_IN_DOUBT','DELIVERED_SIMULATED','DELIVERY_BLOCKED'].includes(run.status)?phases.length-1:phases.indexOf(run.status);
  phases.forEach((p,index)=>{const el=element('div','','phase'+(index<current?' done':index===current?' current':''));el.append(element('b',index<current?'✓':String(index+1).padStart(2,'0')),element('span',index===phases.length-1?'交付 / 核对':labels[p]));$('phase-track').append(el);});
  artifactList=(await api(`/runs/${id}/artifacts`)).items;if(selected!==id)return;
  updateReview();await showArtifact(pane);
}
async function showArtifact(kind){
  pane=kind;document.querySelectorAll('[data-pane]').forEach(e=>e.classList.toggle('active',e.dataset.pane===pane));
  const artifact=artifactList.filter(a=>a.kind===kind).at(-1);artifactText='';$('download').disabled=true;$('artifact-content').replaceChildren();
  if(!artifact){$('artifact-label').textContent=artifactNames[kind]+' · 等待生成';$('artifact-content').textContent=kind==='delivery'?'审阅并批准补丁后，可以生成本地回执。\n此版本不会创建真实 GitHub PR。':'暂未生成此制品。';return;}
  const id=selected;let content=await api(`/runs/${id}/artifacts/${artifact.id}`);if(id!==selected||kind!==pane)return;
  if(typeof content!=='string')content=JSON.stringify(content,null,2);
  if(kind!=='patch'){try{content=JSON.stringify(JSON.parse(content),null,2);}catch{}}
  artifactText=content;$('artifact-label').textContent=artifactNames[kind]+' · sha256 '+artifact.sha256.slice(0,16);$('download').disabled=false;
  if(kind==='patch'){for(const line of content.split('\n')){const cls=line.startsWith('+')?'code-add':line.startsWith('-')?'code-del':line.startsWith('@@')?'code-hunk':'';$('artifact-content').append(element('span',line||' ','code-line '+cls));}}
  else $('artifact-content').textContent=content;
}
function renderEvents(){
  $('event-count').textContent=String(events.length);const list=$('events');list.replaceChildren();
  for(const item of events.slice(-100)){const el=element('div','','event');el.append(element('span',String(item.sequence).padStart(2,'0')),element('strong',item.event_type),element('small',JSON.stringify(item.payload)));list.append(el);}
  list.scrollTop=list.scrollHeight;
}
async function startStream(id){
  streamController=new AbortController();const controller=streamController;let retries=0;
  while(!controller.signal.aborted&&selected===id){
    try{
      const cursor=events.at(-1)?.sequence||0;
      const response=await fetch(`/api/v1/runs/${id}/events?after_seq=${cursor}`,{headers:{Authorization:'Bearer '+token},signal:controller.signal});
      if(!response.ok)throw new Error('事件连接 HTTP '+response.status);
      $('connection').textContent='事件已连接 · '+meta.role;
      const parser=createSSEParser(frame=>{if(frame.type!=='run_event')return;try{events=mergeEvents(events,[JSON.parse(frame.data)]);renderEvents();clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>refreshSelected().catch(e=>notify(e.message)),100);}catch(e){notify('事件解析失败：'+e.message);}});
      const reader=response.body.getReader();const decoder=new TextDecoder();
      while(true){const {value,done}=await reader.read();if(done){parser.push(decoder.decode());break;}parser.push(decoder.decode(value,{stream:true}));}
      await refreshSelected();if(run&&stopped.has(run.status)){$('connection').textContent='已同步 · '+meta.role;return;}
      retries=0;
    }catch(e){if(controller.signal.aborted)return;$('connection').textContent='连接中断 · 重试';if(++retries>=5){notify('事件连接暂不可用，已保留列表轮询。');return;}}
    await new Promise(resolve=>setTimeout(resolve,Math.min(1000*2**retries,8000)));
  }
}
async function action(fn){busy=true;updateReview();try{notify();await fn();await refreshSelected();await refreshList();}catch(e){notify(e.message);}finally{busy=false;updateReview();}}
$('login-form').addEventListener('submit',e=>{e.preventDefault();login($('token').value).catch(error=>{token='';notify(error.message);});});
$('switch-token').addEventListener('click',()=>{streamController?.abort();clearInterval(pollTimer);token='';meta=null;selected=null;run=null;events=[];reviewedBinding='';$('login').hidden=false;$('authenticated').hidden=true;$('connection').textContent='未连接';});
$('project').addEventListener('change',updateObjective);
$('task-form').addEventListener('submit',async e=>{e.preventDefault();await action(async()=>{const created=await api('/runs',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({project_id:$('project').value,objective:$('objective').value,runtime:'fixture'})});await selectRun(created.id);});});
$('refresh').addEventListener('click',()=>action(async()=>{}));
$('cancel').addEventListener('click',()=>action(()=>api(`/runs/${selected}/cancel`,{method:'POST'})));
$('reviewed').addEventListener('change',()=>{reviewedBinding=$('reviewed').checked?reviewBinding(run?.approval,$('delivery-kind').value):'';updateReview();});
async function decide(decision){const a=run.approval;await api(`/approvals/${a.id}/decision`,{method:'POST',body:JSON.stringify({decision,base_commit:a.base_commit,patch_hash:a.patch_hash,validation_digest:a.validation_digest,delivery_kind:$('delivery-kind').value,comment:'Workbench explicitly scoped review'})});}
$('approve').addEventListener('click',()=>action(()=>decide('APPROVED')));
$('reject').addEventListener('click',()=>action(()=>decide('REJECTED')));
$('delivery-kind').addEventListener('change',()=>{reviewedBinding='';$('reviewed').checked=false;updateReview();});
$('deliver').addEventListener('click',()=>action(async()=>{const simulated=run.approval.delivery_kind==='SIMULATED_PR';await api(`/runs/${selected}/deliveries/${simulated?'simulated':'local'}`,{method:'POST',body:JSON.stringify({approval_id:run.approval.id})});pane=simulated?'simulated_delivery':'delivery';}));
$('reconcile').addEventListener('click',()=>action(async()=>{await api(`/runs/${selected}/operations/${run.operation.id}/reconcile`,{method:'POST'});pane='simulated_delivery';}));
$('audit-evidence').addEventListener('click',()=>action(async()=>{const audit=await api(`/runs/${selected}/evidence`);$('evidence-status').textContent=`${audit.checks.length} 项证据检查通过；非测试重跑，非数字签名。`; }));
$('export-evidence').addEventListener('click',()=>action(async()=>{const bundle=await api(`/runs/${selected}/evidence/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`evidence-${selected}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
$('download').addEventListener('click',()=>{const blob=new Blob([artifactText],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`traceforge-${selected.slice(0,8)}-${pane}.${pane==='patch'?'diff':'json'}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
document.querySelectorAll('[data-pane]').forEach(button=>button.addEventListener('click',()=>showArtifact(button.dataset.pane).catch(e=>notify(e.message))));
document.querySelectorAll('[data-section]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-section]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.section-view').forEach(section=>section.hidden=section.id!=='section-'+button.dataset.section);}));

$('check-execution').addEventListener('click',async()=>{
  const button=$('check-execution');button.disabled=true;
  $('execution-readiness').textContent='正在检查本机条件…';
  try{
    const report=await api('/execution/readiness?probe_docker=true');
    $('execution-readiness').textContent=JSON.stringify(report,null,2);
  }catch(error){$('execution-readiness').textContent='预检失败：'+error.message;}
  finally{button.disabled=false;}
});
