import test from 'node:test';
import assert from 'node:assert/strict';
import {followRunEvents} from '../src/traceforge/static/event-stream.mjs';
const frame=(sequence,run_id='r1')=>`event: run_event\ndata: ${JSON.stringify({sequence,run_id})}\n\n`;
const stream=(text)=>new Response(text,{headers:{'Content-Type':'text/event-stream'}});

test('disconnect resumes from last acknowledged event, token only in header',async()=>{
 const ac=new AbortController();const events=[];const requests=[];
 await followRunEvents({token:'synthetic',runId:'r1',signal:ac.signal,pause:async()=>{},onState:()=>{},
   onEvent:e=>{events.push(e.sequence);if(e.sequence===2)ac.abort();},
   fetchImpl:async(url,options)=>{requests.push([url,options]);return stream(frame(requests.length));}});
 assert.deepEqual(events,[1,2]);assert.match(requests[1][0],/after_seq=1$/);
 assert.equal(requests[0][1].headers.Authorization,'Bearer synthetic');
 assert.ok(requests.every(([url])=>!url.includes('synthetic')));
});

test('foreign-run event cannot advance cursor',async()=>{
 const ac=new AbortController();let n=0;const events=[];const urls=[];
 await followRunEvents({token:'t',runId:'r1',signal:ac.signal,pause:async()=>{},onState:()=>{},
  onEvent:e=>{events.push(e.sequence);ac.abort();},fetchImpl:async url=>{
   urls.push(url);return stream(++n===1?frame(1,'other-run'):frame(1));}});
 assert.deepEqual(events,[1]);assert.ok(urls.every(x=>x.endsWith('after_seq=0')));
});

test('gap retries without acknowledging lost events',async()=>{
 const ac=new AbortController();let n=0;const events=[];
 await followRunEvents({token:'t',runId:'r1',signal:ac.signal,pause:async()=>{},onState:()=>{},
  onEvent:e=>{events.push(e.sequence);if(e.sequence===2)ac.abort();},
  fetchImpl:async()=>stream(++n===1?frame(2):frame(1)+frame(2))});
 assert.deepEqual(events,[1,2]);assert.equal(n,2);
});

for(const status of [401,403,404])test(`HTTP ${status} stops, no retry storm`,async()=>{
 let count=0;
 await followRunEvents({token:'t',runId:'r1',signal:new AbortController().signal,
 onState:()=>{},onEvent:()=>assert.fail('no event'),fetchImpl:async()=>{count++;return new Response('',{status});}});
 assert.equal(count,1);
});

test('terminal snapshot finishes without repeated connections',async()=>{
 const events=[];let count=0;
 await followRunEvents({token:'t',runId:'r1',follow:false,signal:new AbortController().signal,
 onState:()=>{},onEvent:e=>events.push(e.sequence),fetchImpl:async()=>{count++;return stream(frame(1));}});
 assert.equal(count,1);assert.deepEqual(events,[1]);
});

test('already aborted stream performs no request',async()=>{
 const ac=new AbortController();ac.abort();
 await followRunEvents({token:'t',runId:'r1',signal:ac.signal,onState:()=>{},onEvent:()=>{},
 fetchImpl:async()=>assert.fail('No request after logout')});
});
