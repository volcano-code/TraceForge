export interface IntentPayload {project_id:string;objective:string;runtime?:'fixture'}
export interface IntentReceipt {id:string;project_id:string;objective:string;runtime:string;request_key:string}
export interface CreateIntent {readonly key:string;readonly payload:Readonly<Required<IntentPayload>>;readonly phase:'prepared'|'submitting'|'uncertain'|'resolved';readonly run:IntentReceipt|null}
export interface IntentManager {
 subscribe(listener:()=>void):()=>void;
 snapshot():CreateIntent|null;
 prepare(payload:IntentPayload):CreateIntent;
 submit(transport:(intent:CreateIntent)=>Promise<IntentReceipt>):Promise<IntentReceipt>;
 startNew():void;
 resetSession():void;
}
export function createIntentManager(newKey?:()=>string):IntentManager;
