import assert from 'node:assert/strict'
import {test} from 'node:test'
import {ref} from 'vue'
import {createProductionAssociationActions} from '../src/renderer/src/store/modules/production-association-actions.ts'
import {associationFixture} from './production-association-fixture.mjs'
function environment(t,callApi) {
  const old=globalThis.window; t.after(()=>{globalThis.window=old}); globalThis.window={nexora:{callApi}}
  const state={server:ref({id:'first',fingerprint:'a'}),user:ref({id:1,permissions:['production.view','inventory.view']}),
    connectionLost:ref(false),busy:ref(false),productionAssociationTarget:ref(null),productionAssociationRecord:ref(null),
    productionAssociationLoading:ref(false),productionAssociationError:ref('')}
  return {state,actions:createProductionAssociationActions(state)}
}
// 迟到响应、换服与权限撤销不能让旧业务来源重新出现。
test('关联只读加载默认无参考，失败保留目标可重试并验证目标一致', async t => {
  const calls=[];let fail=true
  const {state,actions}=environment(t,async(op,input)=>{calls.push([op,input]);if(fail)throw Error('服务暂不可用');return associationFixture()})
  assert.equal(await actions.openProductionAssociations({kind:'work_order',id:1}),false)
  assert.equal(state.productionAssociationTarget.value.id,1);assert.match(state.productionAssociationError.value,/暂不可用/)
  fail=false;assert.equal(await actions.loadProductionAssociations(),true)
  assert.equal(calls[1][1].include_references,false)
  assert.equal(await actions.openProductionAssociations({kind:'work_order',id:2}),false)
  assert.equal(state.productionAssociationRecord.value,null);assert.match(state.productionAssociationError.value,/不一致/)
})

test('切服、换账号或撤销权限清除证据并丢弃迟到响应', async t => {
  let finish;const {state,actions}=environment(t,async()=>new Promise(resolve=>{finish=resolve}))
  const pending=actions.openProductionAssociations({kind:'work_order',id:1})
  state.server.value.id='second';finish(associationFixture());assert.equal(await pending,false)
  assert.equal(state.productionAssociationTarget.value,null);assert.equal(state.productionAssociationRecord.value,null)
  state.user.value.permissions=[];assert.equal(await actions.openProductionAssociations({kind:'work_order',id:1}),false)
})
