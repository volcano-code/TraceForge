export class ApiError extends Error {
  constructor(public status:number, public code:string, message:string) {super(message);this.name='ApiError';}
}
export async function api<T>(token:string,path:string,options:RequestInit={}):Promise<T> {
  const headers=new Headers(options.headers);headers.set('Authorization',`Bearer ${token}`);
  if(options.body)headers.set('Content-Type','application/json');
  const response=await fetch(`/api/v1${path}`,{...options,headers});
  if(!response.ok){let body:{error?:{code:string;message:string}}={};try{body=await response.json();}catch{}
    throw new ApiError(response.status,body.error?.code||'HTTP_ERROR',body.error?.message||`HTTP ${response.status}`);}
  return response.json() as Promise<T>;
}
export async function artifactText(token:string,runId:string,id:string):Promise<string>{
  const response=await fetch(`/api/v1/runs/${runId}/artifacts/${id}`,{headers:{Authorization:`Bearer ${token}`}});
  if(!response.ok)throw new ApiError(response.status,'ARTIFACT_ERROR','制品不可用或完整性检查失败');return response.text();
}
