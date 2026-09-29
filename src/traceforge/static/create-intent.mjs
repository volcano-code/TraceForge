/** One submission intent per authenticated in-memory session. Never stores tokens.
 * A transport error is an UNKNOWN outcome, not permission to allocate another key.
 */
export function createIntentManager(newKey = () => crypto.randomUUID()) {
  let current = null, pending = null, generation = 0;
  const listeners = new Set();
  const publish = value => { current = value; for (const listener of listeners) listener(); };
  const payloadOf = value => Object.freeze({project_id:value.project_id, objective:value.objective, runtime:'fixture'});
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    snapshot() { return current; },
    prepare(value) {
      const payload = payloadOf(value);
      if (current) {
        if (JSON.stringify(payload) !== JSON.stringify(current.payload))
          throw new Error('已有提交意图，请先核实原任务；确认成功后才能开始新任务。');
        return current;
      }
      const key = newKey();
      if (typeof key !== 'string' || key.length < 8 || key.length > 128) throw new Error('Invalid intent key');
      publish(Object.freeze({key, payload, phase:'prepared', run:null}));
      return current;
    },
    submit(transport) {
      if (!current) return Promise.reject(new Error('No prepared intent'));
      if (pending) return pending;
      if (current.phase === 'resolved') return Promise.resolve(current.run);
      const intent = current, epoch = generation;
      publish(Object.freeze({...intent, phase:'submitting'}));
      const promise = Promise.resolve().then(() => {
        if (epoch !== generation) throw new Error('登录会话已经结束，提交已停止。');
        return transport(intent);
      }).then(run => {
        if (epoch !== generation) throw new Error('登录会话已经结束；请从任务列表核实结果。');
        if (!run || typeof run.id !== 'string' || !run.id || run.request_key !== intent.key ||
            run.project_id !== intent.payload.project_id || run.objective !== intent.payload.objective || run.runtime !== 'fixture')
          throw new Error('创建回执与提交意图不匹配，请使用原提交重试核实。');
        publish(Object.freeze({...intent, phase:'resolved', run:Object.freeze({...run})}));
        return current.run;
      }).catch(error => {
        if (epoch === generation) publish(Object.freeze({...intent, phase:'uncertain'}));
        throw error;
      }).finally(() => { if (epoch === generation) pending = null; });
      pending = promise;
      return promise;
    },
    startNew() {
      if (current && current.phase !== 'resolved')
        throw new Error('原任务结果尚未确认，不能自动换键创建另一个任务。');
      generation++; pending = null; publish(null);
    },
    resetSession() { generation++; pending = null; publish(null); },
  };
}
