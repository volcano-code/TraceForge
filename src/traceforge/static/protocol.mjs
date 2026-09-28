/** Streaming SSE parser; transport chunks are not event boundaries. */
export function createSSEParser(onEvent) {
  let buffer = '';
  return {
    push(chunk) {
      buffer += chunk;
      buffer = buffer.replace(/\r\n/g, '\n');
      let index;
      while ((index = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, index); buffer = buffer.slice(index + 2);
        let id = '', type = 'message'; const data = [];
        for (const line of frame.split('\n')) {
          if (!line || line.startsWith(':')) continue;
          const colon = line.indexOf(':');
          const key = colon < 0 ? line : line.slice(0, colon);
          let value = colon < 0 ? '' : line.slice(colon + 1);
          if (value.startsWith(' ')) value = value.slice(1);
          if (key === 'id' && !value.includes('\0')) id = value;
          if (key === 'event') type = value;
          if (key === 'data') data.push(value);
        }
        if (data.length) onEvent({id, type, data: data.join('\n')});
      }
    },
    pending() { return buffer; }
  };
}

export function mergeEvents(previous, incoming) {
  const bySequence = new Map(previous.map(event => [event.sequence, event]));
  for (const event of incoming) {
    if (Number.isSafeInteger(event.sequence) && event.sequence > 0) bySequence.set(event.sequence, event);
  }
  return [...bySequence.values()].sort((a,b) => a.sequence - b.sequence);
}

export function reviewBinding(approval, deliveryKind = approval?.delivery_kind || "LOCAL_RECEIPT") {
  return approval ? [approval.base_commit, approval.patch_hash, approval.validation_digest, deliveryKind].join(':') : '';
}

export function canApprove(run, role, reviewedBinding, deliveryKind = run?.approval?.delivery_kind || "LOCAL_RECEIPT") {
  return ['LOCAL_RECEIPT','SIMULATED_PR'].includes(deliveryKind) && role === 'reviewer' && run?.status === 'WAITING_APPROVAL'
    && run.approval?.decision === 'PENDING' && reviewedBinding === reviewBinding(run.approval, deliveryKind)
    && Math.floor(Date.now() / 1000) < run.approval.expires_at;
}

export const stopped = new Set(['WAITING_APPROVAL','APPROVED','DELIVERED_LOCAL','REJECTED','CANCELLED','FAILED','DELIVERY_IN_DOUBT','DELIVERED_SIMULATED','DELIVERY_BLOCKED']);
export const phases = ['QUEUED','PREPARING','REPRODUCING','PATCHING','VERIFYING','WAITING_APPROVAL','APPROVED','DELIVERED_LOCAL'];
export const labels = {
  QUEUED:'已入队', PREPARING:'准备工作区', REPRODUCING:'复现缺陷', PATCHING:'生成样例补丁',
  VERIFYING:'独立验证', WAITING_APPROVAL:'等待审阅', APPROVED:'已批准', DELIVERED_LOCAL:'本地交付完成',
  DELIVERING:'提交中（模拟）', DELIVERY_IN_DOUBT:'结果待核实', DELIVERED_SIMULATED:'模拟交付已核实', DELIVERY_BLOCKED:'交付已阻止',
  REJECTED:'已拒绝', CANCELLED:'已取消', FAILED:'失败'
};
