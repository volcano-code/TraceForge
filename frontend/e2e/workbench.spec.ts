import {test,expect,type Page,type APIRequestContext} from '@playwright/test';
const reviewer=process.env.TF_REVIEWER_TOKEN;
const developer=process.env.CI?'e2e-only-developer-not-a-real-secret':process.env.TF_DEVELOPER_TOKEN;
const API=process.env.TF_API_URL||'http://127.0.0.1:8000';
function credential(value:string|undefined){if(!value)throw new Error('E2E credentials are required, never silently skip');return value;}
const auth=(token:string)=>({Authorization:`Bearer ${token}`});
async function login(page:Page,token=credential(reviewer)){
 await page.goto('/');await page.getByLabel('访问令牌').fill(token);
 await page.getByRole('button',{name:'连接工作区'}).click();
 await expect(page.getByRole('heading',{name:'新建验证任务'})).toBeVisible();
}
async function fill(page:Page,objective:string){
 await expect(page.locator('#task-project option')).toHaveCount(4);
 await page.getByLabel('受控样例',{exact:true}).selectOption({label:'删除后分页越界'});
 await page.getByLabel('问题描述',{exact:true}).fill(objective);
}
async function create(page:Page,objective:string){
 await fill(page,objective);await page.getByRole('button',{name:'创建任务',exact:true}).click();
 await expect(page).toHaveURL(/\/runs\/[a-f0-9-]+$/);
 await expect(page.locator('.status')).toHaveText('等待审阅',{timeout:30000});
 return page.url().split('/').at(-1)!;
}
async function data(request:APIRequestContext,id:string){
 const r=await request.get(`${API}/api/v1/runs/${id}`,{headers:auth(credential(reviewer))});expect(r.ok()).toBeTruthy();return r.json();
}
async function review(page:Page){
 await page.getByRole('button',{name:'验证报告',exact:true}).click();
 await expect(page.locator('.code-area')).toContainText('"verified": true');
 await page.getByRole('button',{name:'代码补丁',exact:true}).click();
 await expect(page.locator('.code-area')).toContainText('@@');
 await page.getByRole('checkbox').check();
}

test('authenticated workbench lists real fixture projects',async({page})=>{
 await login(page);await page.getByRole('link',{name:'▦ 样例项目'}).click();
 await expect(page.getByRole('heading',{name:'删除后分页越界'})).toBeVisible();
});

test('committed response loss then navigation and retry creates one run, reviews and delivers locally',async({page,request},info)=>{
 await login(page);const objective=`e2e lost response ${Date.now()}`;const keys:string[]=[];let first:any;
 await page.route('**/api/v1/runs',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  keys.push(route.request().headers()['idempotency-key']);
  const response=await route.fetch();expect(response.status()).toBe(201);
  if(keys.length===1){first=await response.json();await response.dispose();return route.abort('connectionreset');}
  await route.fulfill({response});await response.dispose();
 });
 await fill(page,objective);await page.getByRole('button',{name:'创建任务',exact:true}).click();
 await expect(page.getByRole('alert')).toBeVisible();
 await expect(page.getByLabel('受控样例',{exact:true})).toBeDisabled();
 await page.getByRole('link',{name:'▦ 样例项目'}).click();await page.getByRole('link',{name:'◈ 验证任务'}).click();
 await expect(page.getByTestId('create-intent-status')).toContainText(keys[0]);
 await page.getByRole('button',{name:'核实并重试原任务'}).click();
 await expect(page).toHaveURL(new RegExp(`/runs/${first.id}$`));expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);
 await expect(page.locator('.status')).toHaveText('等待审阅',{timeout:30000});
 const listed=await request.get(`${API}/api/v1/runs?limit=100`,{headers:auth(credential(reviewer))});
 expect((await listed.json()).items.filter((r:any)=>r.request_key===keys[0])).toHaveLength(1);
 const events=await request.get(`${API}/api/v1/runs/${first.id}/events?stream=false`,{headers:auth(credential(reviewer))});
 expect((await events.json()).items.filter((e:any)=>e.event_type==='RUN_CREATED')).toHaveLength(1);
 await review(page);await page.getByRole('button',{name:'批准当前版本'}).click();
 await expect(page.locator('.status')).toHaveText('已批准');
 await page.getByRole('button',{name:'生成本地回执',exact:true}).click();
 await expect(page.locator('.status')).toHaveText('本地交付完成');
 await page.getByRole('button',{name:'本地回执',exact:true}).click();await expect(page.locator('.code-area')).toContainText('"real_github_pr_created": false');
 await page.screenshot({path:info.outputPath('local-delivery.png'),fullPage:true});
 await page.getByRole('link',{name:'◈ 验证任务'}).click();await page.getByRole('button',{name:'开始新任务'}).click();
 await expect(page.getByLabel('受控样例',{exact:true})).toBeEnabled();
});

test('scope change invalidates review and permits only bound simulated delivery',async({page,request},info)=>{
 await login(page);const id=await create(page,`e2e scope ${Date.now()}`);await review(page);
 await page.getByLabel('批准的交付范围').selectOption('SIMULATED_PR');
 await expect(page.getByRole('checkbox')).not.toBeChecked();await expect(page.getByRole('button',{name:'批准当前版本'})).toBeDisabled();
 await review(page);await page.getByRole('button',{name:'批准当前版本'}).click();
 await expect(page.locator('.status')).toHaveText('已批准');
 const run=await data(request,id);
 const invalid=await request.post(`${API}/api/v1/runs/${id}/deliveries/local`,{headers:auth(credential(reviewer)),data:{approval_id:run.approval.id}});expect(invalid.status()).toBe(403);
 await page.getByRole('button',{name:'提交到独立模拟端',exact:true}).click();await expect(page.locator('.status')).toHaveText('模拟交付已核实');
 const state=await data(request,id);
 const replay=await request.post(`${API}/api/v1/runs/${id}/deliveries/simulated`,{headers:auth(credential(reviewer)),data:{approval_id:run.approval.id}});expect(replay.ok()).toBeTruthy();expect((await replay.json()).id).toBe(state.operation.id);
 await page.getByRole('button',{name:'模拟端回执',exact:true}).click();await expect(page.locator('.code-area')).toContainText('false');
 await page.screenshot({path:info.outputPath('simulated-delivery.png'),fullPage:true});
});

test('rejection blocks delivery at server as well as UI',async({page,request})=>{
 await login(page);const id=await create(page,`e2e reject ${Date.now()}`);await page.getByRole('button',{name:'拒绝',exact:true}).click();await expect(page.locator('.status')).toHaveText('已拒绝');
 const run=await data(request,id);const response=await request.post(`${API}/api/v1/runs/${id}/deliveries/local`,{headers:auth(credential(reviewer)),data:{approval_id:run.approval.id}});expect(response.status()).toBe(403);expect(run.operation).toBeNull();
});

test('developer cannot approve even with a forged API request',async({page,request})=>{
 const token=credential(developer);await login(page,token);const id=await create(page,`e2e developer ${Date.now()}`);await review(page);await expect(page.getByRole('button',{name:'批准当前版本'})).toBeDisabled();
 const run=await data(request,id),a=run.approval;
 const response=await request.post(`${API}/api/v1/approvals/${a.id}/decision`,{headers:auth(token),data:{decision:'APPROVED',base_commit:a.base_commit,patch_hash:a.patch_hash,validation_digest:a.validation_digest,delivery_kind:'LOCAL_RECEIPT'}});expect(response.status()).toBe(403);
 expect((await data(request,id)).approval.decision).toBe('PENDING');
});

test('cancelled task cannot be approved and has no delivery',async({page,request})=>{
 await login(page);const id=await create(page,`e2e cancel ${Date.now()}`);await page.getByRole('button',{name:'取消',exact:true}).click();await expect(page.locator('.status')).toHaveText('已取消');
 await expect(page.getByRole('button',{name:'批准当前版本'})).toBeDisabled();expect((await data(request,id)).operation).toBeNull();
});

test('stale patch approval is rejected without side effects',async({page,request})=>{
 await login(page);const id=await create(page,`e2e stale ${Date.now()}`);await review(page);
 await page.route('**/api/v1/approvals/*/decision',async route=>{const body=route.request().postDataJSON();await route.continue({postData:JSON.stringify({...body,patch_hash:'0'.repeat(64)})});});
 await page.getByRole('button',{name:'批准当前版本'}).click();await expect(page.getByRole('alert')).toContainText('Approval must bind');
 const run=await data(request,id);expect(run.status).toBe('WAITING_APPROVAL');expect(run.approval.decision).toBe('PENDING');expect(run.operation).toBeNull();
});

test('historical release evidence never claims current-host authority',async({page})=>{
 await login(page);await page.getByRole('link',{name:'◎ 验收状态'}).click();
 await expect(page.getByRole('heading',{name:'技术验收状态'})).toBeVisible();
 await expect(page.getByText('历史验收提交：')).toBeVisible();await expect(page.getByText(/coding_agent_ready = false/)).toBeVisible();
 await expect(page.getByText('完整编译未在当前环境通过验证')).toHaveCount(0);
});
