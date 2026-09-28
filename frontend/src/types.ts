export interface Project {id:string;name:string;fixture_id:string;base_commit:string;created_at:number}
export interface TestResult {tests_run:number;failures:string[];errors:string[];exit_code:number;log:string;grader_sha256:string}
export interface Approval {id:string;run_id:string;base_commit:string;patch_hash:string;validation_digest:string;decision:'PENDING'|'APPROVED'|'REJECTED';delivery_kind:'LOCAL_RECEIPT'|'SIMULATED_PR';expires_at:number}
export interface Run {id:string;project_id:string;objective:string;runtime:string;status:string;version:number;base_commit:string;created_at:number;failure_code:string|null;
  data:{before?:TestResult;after?:TestResult;patch_artifact_id?:string;validation_artifact_id?:string;patch_hash?:string;validation_digest?:string};
  approval?:Approval|null;operation?:{id:string;external_ref:string|null;status:string;kind:string;last_error:string|null}|null}
export interface RunEvent {id:string;run_id:string;sequence:number;state_version:number;event_type:string;actor:string;payload:Record<string,unknown>;created_at:number}
export interface Artifact {id:string;kind:string;sha256:string;byte_count:number;media_type:string}
export interface Meta {version:string;role:'developer'|'reviewer';runtime:string;real_llm_connected:boolean;real_github_connected:boolean;fixtures:{id:string;title:string;objective:string}[]}
