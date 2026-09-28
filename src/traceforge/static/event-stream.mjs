import {createSSEParser} from './protocol.mjs';

function wait(ms, signal) {
  return new Promise(resolve => {
    if (signal.aborted) return resolve();
    const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); };
    const timer = setTimeout(done, ms);
    signal.addEventListener('abort', done, {once:true});
  });
}

/** Recover the event stream with a scoped cursor; never place credentials in URLs. */
export async function followRunEvents({token, runId, signal, onEvent, onState,
  afterSequence=0, follow=true, fetchImpl=globalThis.fetch, pause=wait}) {
  let cursor=afterSequence, failures=0;
  while (!signal.aborted) {
    let reader;
    try {
      const response=await fetchImpl(`/api/v1/runs/${encodeURIComponent(runId)}/events?after_seq=${cursor}`,
        {headers:{Authorization:`Bearer ${token}`},signal});
      if ([401,403,404].includes(response.status)) { onState('需要重新认证或任务不可用'); return; }
      if (!response.ok || !response.body) throw new Error('SSE unavailable');
      onState('已连接');
      const parser=createSSEParser(frame => {
        if (signal.aborted || frame.type!=='run_event') return;
        const event=JSON.parse(frame.data);
        if (event.run_id!==runId || !Number.isSafeInteger(event.sequence) || event.sequence<=0)
          throw new Error('Invalid event scope');
        if (event.sequence<=cursor) return;
        if (event.sequence!==cursor+1) throw new Error('Event gap; reconnect from acknowledged cursor');
        onEvent(event);
        cursor=event.sequence; failures=0;
      });
      reader=response.body.getReader();
      const decoder=new TextDecoder();
      while (!signal.aborted) {
        const {done,value}=await reader.read();
        if (done) {parser.push(decoder.decode());break;}
        parser.push(decoder.decode(value,{stream:true}));
        if (parser.pending().length>524288) throw new Error('SSE frame too large');
      }
      if (signal.aborted) return;
      if (!follow) {onState('已同步');return;}
      onState('连接结束，正在续读');
    } catch {
      if (signal.aborted) return;
      onState('连接中断，正在重连');
    } finally {
      if (reader) {try {await reader.cancel();} catch {} reader.releaseLock();}
    }
    await pause(Math.min(30000,500*2**Math.min(failures++,6)),signal);
  }
}
