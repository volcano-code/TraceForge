import {afterEach,describe,expect,it,vi} from 'vitest';
import {api,ApiError} from './api';
afterEach(()=>vi.unstubAllGlobals());
describe('API boundary',()=>{
 it('transmits token in header, not URL',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({ok:true}),{status:200}));vi.stubGlobal('fetch',fetch);
  await api('secret-value','/meta');const[url,options]=fetch.mock.calls[0];expect(url).not.toContain('secret-value');expect(options.headers.get('Authorization')).toBe('Bearer secret-value');
 });
 it('preserves structured errors',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({error:{code:'STALE_APPROVAL',message:'Changed patch'}}),{status:409})));
  await expect(api('token','/meta')).rejects.toMatchObject({status:409,code:'STALE_APPROVAL'});
 });
});
