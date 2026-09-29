import {useEffect,useSyncExternalStore} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {Link,useNavigate} from '@tanstack/react-router';
import {useForm} from 'react-hook-form';
import {z} from 'zod';
import {useAuth} from './auth';
import {api} from './api';
import type {Project,Run} from './types';
import {labels} from '../../src/traceforge/static/protocol.mjs';
const schema=z.object({project_id:z.string().min(1),objective:z.string().min(5).max(4000)});
type Form=z.infer<typeof schema>;

export function Runs(){
 const {token,meta,intents}=useAuth();
 const intent=useSyncExternalStore(intents.subscribe,intents.snapshot,intents.snapshot);
 const navigate=useNavigate(),cache=useQueryClient();
 const projects=useQuery({queryKey:['projects'],queryFn:()=>api<{items:Project[]}>(token,'/projects')});
 const list=useQuery({queryKey:['runs'],queryFn:()=>api<{items:Run[];total:number}>(token,'/runs'),refetchInterval:3000});
 const {register,handleSubmit,setValue,reset,setError,formState:{errors}}=useForm<Form>();
 useEffect(()=>{if(intent){setValue('project_id',intent.payload.project_id);setValue('objective',intent.payload.objective);}},[intent?.key,setValue]);
 const create=useMutation({
  mutationFn:(values:Form)=>{
   intents.prepare(values);
   return intents.submit(i=>api<Run>(token,'/runs',{method:'POST',headers:{'Idempotency-Key':i.key},
     signal:AbortSignal.timeout(15000),body:JSON.stringify(i.payload)}));
  },
  onSuccess:async run=>{await cache.invalidateQueries({queryKey:['runs']});await navigate({to:'/runs/$runId',params:{runId:run.id}});},
 });
 const error=projects.error||list.error||create.error;
 const submit=async(values:Form)=>{const parsed=schema.safeParse(intent?.payload||values);if(!parsed.success){setError('objective',{message:'请选择项目，并输入 5–4000 字问题描述。'});return;}create.mutate(parsed.data);};
 return <>
  <div className="stats">
   <article><span>任务总数</span><strong>{list.data?.total??0}</strong><small>本地数据库</small></article>
   <article><span>执行模式</span><strong>{meta?.runtime||'未连接'}</strong><small>非自主 Coding Agent</small></article>
   <article><span>模型连接</span><strong>{meta?.real_llm_connected?'已连接':'未接入'}</strong><small>不将样例计为模型修复</small></article>
   <article><span>样例类型</span><strong>{projects.data?.items.length??0}</strong><small>不是 Agent Benchmark</small></article>
  </div>
  {error&&<div className="alert" role="alert">{error instanceof Error?error.message:String(error)}</div>}
  <div className="workspace-grid"><section className="card"><h2>新建验证任务</h2>
   {intent&&<div role="status" data-testid="create-intent-status" className="notice"><span>{intent.phase==='resolved'?'原任务已经确认；返回原任务或明确开始新任务。':'提交意图已锁定。结果不明时只使用原键、原内容核实，不自动创建另一个任务。'} 请求标识：{intent.key}</span></div>}
   <form onSubmit={e=>{if(intent){e.preventDefault();void submit(intent.payload);}else void handleSubmit(submit)(e);}}>
    <label htmlFor="task-project">受控样例</label>
    <select id="task-project" disabled={!!intent} {...register('project_id',{required:true,onChange:e=>{
     const project=projects.data?.items.find(p=>p.id===e.target.value);
     setValue('objective',meta?.fixtures.find(f=>f.id===project?.fixture_id)?.objective||'');
    }})}><option value="">选择项目</option>{projects.data?.items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>
    <label htmlFor="task-objective">问题描述</label>
    <textarea id="task-objective" readOnly={!!intent} rows={5} {...register('objective',{required:true})}/>
    {errors.objective&&<p role="alert">{errors.objective.message}</p>}
    <button className="button wide" disabled={create.isPending||intent?.phase==='submitting'}>
     {intent?.phase==='resolved'?'返回已创建任务':intent?'核实并重试原任务':'创建任务'}
    </button>
    {intent?.phase==='resolved'&&<button type="button" className="button quiet" onClick={()=>{intents.startNew();create.reset();reset({project_id:'',objective:''});}}>开始新任务</button>}
   </form>
   <p className="helper">待核实意图保存在本次登录会话内，跨页面导航保留；刷新或退出后先查任务列表。自定义描述不会令 Fixture 变成自主 Agent。</p>
  </section><section className="card"><h2>执行记录</h2>
   {list.isPending?<p>正在读取任务…</p>:list.data?.items.length?list.data.items.map(run=><Link key={run.id} to="/runs/$runId" params={{runId:run.id}} className="run-item"><strong>{projects.data?.items.find(p=>p.id===run.project_id)?.name||run.objective}</strong><small><span>{run.id.slice(0,8)}</span><span>{(labels as Record<string,string>)[run.status]||run.status}</span></small></Link>):<p className="helper">暂无任务。先运行一个受控样例。</p>}
  </section></div>
 </>;
}
