import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { createWarehouseActions } from '../src/renderer/src/store/modules/warehouse-actions.ts'

// 用真实仓库操作验证新建请求边界，原单即使包含历史字段也不能把它们复制回服务端。
function fixture() {
 const source={id:8,document_no:'QTRK-OLD',status:'cancelled',warehouse_id:1,reason:'gift',note:'赠品',reference:'REF',
  approval:{status:'rejected'},cancelled_by:1,cancelled_at:'2026-10-08',
  lines:[{id:77,material_id:2,quantity:'2.125',physical_lots:[{id:20,quantity:'2.125'}]}]}
 const state={otherInbounds:ref([source,{...source,id:9}]),otherInboundReopenForms:ref({}),
  otherInboundForm:ref({warehouse_id:1,reason:'other',note:'正在填写',reference:'DRAFT',lines:[{material_id:3,quantity:'7'}]}),
  user:ref({id:1,permissions:['other_inbound.create']}),busy:ref(false),connectionLost:ref(false),error:ref(''),
  materials:ref([{id:2},{id:3}]),warehouses:ref([{id:1}])}
 let fail=false
 const calls=[]
 globalThis.window={nexora:{callApi:async(operation,input)=>{
  calls.push([operation,input]);if(fail)throw Error('保存失败')
  return {id:100,document_no:'QTRK-NEW',status:'draft',...input}
 }}}
 const actions=createWarehouseActions(state,async(action)=>{
  state.busy.value=true
  try {await action();state.error.value=''}catch(error){state.error.value=error.message}finally{state.busy.value=false}
 })
 return {state,actions,calls,setFail:value=>{fail=value}}
}

test('重开只复制可编辑字段，按原单保留独立草稿且不覆盖正常新建',async t=>{
 const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
 const {state,actions,calls,setFail}=fixture()
 const original=JSON.stringify(state.otherInbounds.value),normal=JSON.stringify(state.otherInboundForm.value)
 assert.equal(actions.prepareOtherInboundReopen(8),true)
 const draft=state.otherInboundReopenForms.value[8]
 assert.deepEqual(draft,{warehouse_id:1,reason:'gift',note:'赠品',reference:'REF',lines:[{material_id:2,quantity:'2.125'}]})
 assert.equal(calls.length,0)
 draft.lines[0].quantity='3';draft.note='更正说明'
 actions.prepareOtherInboundReopen(9)
 actions.prepareOtherInboundReopen(8)
 assert.equal(state.otherInboundReopenForms.value[8],draft)
 assert.equal(state.otherInboundReopenForms.value[9].lines[0].quantity,'2.125')
 setFail(true)
 await actions.createReopenedOtherInbound(8)
 assert.equal(state.error.value,'保存失败')
 assert.equal(state.otherInboundReopenForms.value[8],draft)
 setFail(false)
 await actions.createReopenedOtherInbound(8)
 assert.equal(state.otherInboundReopenForms.value[8],undefined)
 assert.ok(state.otherInboundReopenForms.value[9])
 assert.deepEqual(calls.at(-1),['reopenOtherInbound',{inboundId:8,warehouse_id:1,reason:'gift',note:'更正说明',reference:'REF',lines:[{material_id:2,quantity:'3'}]}])
 assert.equal(state.otherInbounds.value[0].reopened_as_id,100)
 assert.equal(actions.prepareOtherInboundReopen(8),false)
 assert.equal(JSON.stringify({...state.otherInbounds.value[0],reopened_as_id:undefined}),JSON.stringify(JSON.parse(original)[0]))
 assert.equal(JSON.stringify(state.otherInboundForm.value),normal)
 // 成功后旧回调不能再次创建；并发点击也只能发出一次新建请求。
 await actions.createReopenedOtherInbound(8)
 assert.equal(calls.length,2)
 await Promise.all([actions.createReopenedOtherInbound(9),actions.createReopenedOtherInbound(9)])
 assert.equal(calls.length,3)
})

test('重开重新检查权限、终态、连接及物料仓库有效性，阻止过期入口',async t=>{
 const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
 const {state,actions,calls}=fixture()
 actions.prepareOtherInboundReopen(8)
 for(const flag of ['busy','connectionLost']) {
  state[flag].value=true
  assert.equal(actions.prepareOtherInboundReopen(9),false)
  await actions.createReopenedOtherInbound(8)
  state[flag].value=false
 }
 state.user.value.permissions=[]
 assert.equal(actions.prepareOtherInboundReopen(9),false)
 await actions.createReopenedOtherInbound(8)
 state.user.value.permissions=['other_inbound.create']
 for(const status of ['draft','posted']) {
  state.otherInbounds.value[0].status=status
  assert.equal(actions.prepareOtherInboundReopen(8),false)
  await actions.createReopenedOtherInbound(8)
 }
 state.otherInbounds.value[0].status='cancelled'
 state.materials.value=[]
 await actions.createReopenedOtherInbound(8)
 assert.match(state.error.value,/物料已不可用/)
 state.materials.value=[{id:2}];state.warehouses.value=[]
 await actions.createReopenedOtherInbound(8)
 assert.match(state.error.value,/仓库/)
 assert.equal(calls.length,0)
 assert.ok(state.otherInboundReopenForms.value[8])
})

// 冲销与取消同样保留独立草稿，已成功重开的旧快照也不能再次进入编辑器。
test('冲销终态可重开，原单已有派生单时阻止打开和保存',async t=>{
 const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
 const {state,actions,calls}=fixture()
 state.otherInbounds.value[0].status='posted';state.otherInbounds.value[0].reversal_id=20
 assert.equal(actions.prepareOtherInboundReopen(8),true)
 state.otherInbounds.value[0].reopened_as_id=100
 assert.equal(actions.prepareOtherInboundReopen(8),false)
 await actions.createReopenedOtherInbound(8)
 assert.equal(calls.length,0)
 state.otherInbounds.value[0].reopened_as_id=null
 await actions.createReopenedOtherInbound(8)
 assert.equal(calls.length,1)
 assert.equal(calls[0][0],'reopenOtherInbound')
 assert.equal(state.otherInbounds.value[0].status,'posted')
 assert.equal(state.otherInbounds.value[0].reversal_id,20)
 assert.equal(actions.prepareOtherInboundReopen(8),false)
})
