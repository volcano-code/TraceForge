import {useEffect,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {mergeEvents,stopped} from '../../src/traceforge/static/protocol.mjs';
import {followRunEvents} from '../../src/traceforge/static/event-stream.mjs';
import type {RunEvent} from './types';
export function useRunEvents(token:string,runId:string,status:string|undefined){
 const [events,setEvents]=useState<RunEvent[]>([]);
 const [connection,setConnection]=useState('连接中');
 const cursor=useRef(0);const cache=useQueryClient();
 useEffect(()=>{setEvents([]);cursor.current=0;},[runId,token]);
 useEffect(()=>{
  if(!token)return;
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
  void followRunEvents({token,runId,signal:controller.signal,afterSequence:cursor.current,
    follow:!stopped.has(status||''),onState:setConnection,onEvent:raw=>{
      if(controller.signal.aborted)return;
      const event=raw as unknown as RunEvent;
      cursor.current=event.sequence;
      setEvents(previous=>mergeEvents(previous,[event]));
      clearTimeout(timer);
      timer=setTimeout(()=>{
        void cache.invalidateQueries({queryKey:['run',runId]});
        void cache.invalidateQueries({queryKey:['artifacts',runId]});
      },100);
    }});
  return()=>{controller.abort();clearTimeout(timer);};
 },[token,runId,status,cache]);
 return {events,connection};
}
