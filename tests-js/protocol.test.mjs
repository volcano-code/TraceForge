import test from 'node:test';
import assert from 'node:assert/strict';
import {createSSEParser,mergeEvents,reviewBinding,canApprove} from '../src/traceforge/static/protocol.mjs';

test('frames survive arbitrary chunks',()=>{const events=[];const p=createSSEParser(e=>events.push(e));p.push('id: 1\nevent: run_');p.push('event\ndata: {"ok":');p.push('true}\n\n');assert.deepEqual(events,[{id:'1',type:'run_event',data:'{"ok":true}'}]);});
test('heartbeats produce no application events',()=>{const events=[];createSSEParser(e=>events.push(e)).push(': heartbeat\n\n');assert.equal(events.length,0);});
test('multiline data preserved',()=>{let event;createSSEParser(e=>event=e).push('data: one\ndata: two\n\n');assert.equal(event.data,'one\ntwo');});
test('CRLF normalized including split boundaries',()=>{const events=[];const p=createSSEParser(e=>events.push(e));p.push('data: hi\r');p.push('\n\r\n');assert.equal(events[0].data,'hi');});
test('multiple frames dispatched',()=>{const events=[];createSSEParser(e=>events.push(e)).push('data: 1\n\ndata: 2\n\n');assert.equal(events.length,2);});
test('unfinished frame buffered',()=>{const events=[];const p=createSSEParser(e=>events.push(e));p.push('data: abc\n');assert.equal(events.length,0);assert.equal(p.pending(),'data: abc\n');});
test('unicode content preserved',()=>{let e;createSSEParser(x=>e=x).push('data: 验证完成\n\n');assert.equal(e.data,'验证完成');});
test('duplicate events merged and sorted',()=>{assert.deepEqual(mergeEvents([{sequence:2},{sequence:1}],[{sequence:2},{sequence:3}]).map(e=>e.sequence),[1,2,3]);});
test('bad event sequences dropped',()=>{assert.equal(mergeEvents([],[{sequence:-1},{sequence:'2'},{sequence:NaN}]).length,0);});
test('no approval without explicit bound review',()=>{const a={base_commit:'base',patch_hash:'patch',validation_digest:'report',decision:'PENDING',expires_at:Date.now()/1000+60};assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'reviewer',''),false);assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'reviewer',reviewBinding(a)),true);});
test('changed patch clears effective permission',()=>{const a={base_commit:'base',patch_hash:'patch',validation_digest:'report',decision:'PENDING',expires_at:Date.now()/1000+60};const binding=reviewBinding(a);a.patch_hash='changed';assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'reviewer',binding),false);});
test('developer cannot approve',()=>{const a={base_commit:'base',patch_hash:'patch',validation_digest:'report',decision:'PENDING',expires_at:Date.now()/1000+60};assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'developer',reviewBinding(a)),false);});
test('expired approval disabled',()=>{const a={base_commit:'base',patch_hash:'patch',validation_digest:'report',decision:'PENDING',expires_at:1};assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'reviewer',reviewBinding(a)),false);});
test('delivery action change invalidates reviewed binding',()=>{const a={base_commit:'base',patch_hash:'patch',validation_digest:'report',delivery_kind:'LOCAL_RECEIPT',decision:'PENDING',expires_at:Date.now()/1000+60};const run={status:'WAITING_APPROVAL',approval:a};const bound=reviewBinding(a,'LOCAL_RECEIPT');assert.equal(canApprove(run,'reviewer',bound,'SIMULATED_PR'),false);assert.equal(canApprove(run,'reviewer',reviewBinding(a,'SIMULATED_PR'),'SIMULATED_PR'),true);});
test('unrecognized delivery action cannot be approved by UI',()=>{const a={base_commit:'b',patch_hash:'p',validation_digest:'v',decision:'PENDING',expires_at:Date.now()/1000+60};assert.equal(canApprove({status:'WAITING_APPROVAL',approval:a},'reviewer',reviewBinding(a,'REAL_PR'),'REAL_PR'),false);});
