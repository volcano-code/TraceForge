export function followRunEvents(options: {
 token: string; runId: string; signal: AbortSignal;
 onEvent: (event: {run_id:string;sequence:number;[key:string]:unknown}) => void;
 onState: (state:string) => void; afterSequence?:number; follow?:boolean;
 fetchImpl?:typeof fetch; pause?:(ms:number, signal:AbortSignal)=>Promise<void>;
}): Promise<void>;
