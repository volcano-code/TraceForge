export interface SSEFrame { id: string; type: string; data: string }
export interface Binding { base_commit: string; patch_hash: string; validation_digest: string;
  delivery_kind?: string; expires_at: number; decision: string }
export function createSSEParser(callback: (frame: SSEFrame) => void): { push(chunk: string): void; pending(): string };
export function mergeEvents<T extends {sequence: number}>(previous: T[], incoming: T[]): T[];
export function reviewBinding(approval: Binding | null | undefined, deliveryKind?: string): string;
export function canApprove(run: {status: string; approval?: Binding | null} | null | undefined,
  role: string | undefined, reviewedBinding: string, deliveryKind?: string): boolean;
export const stopped: Set<string>;
export const phases: string[];
export const labels: Record<string, string>;
