import assert from 'node:assert/strict'
import {test} from 'node:test'
import {effectScope, ref} from 'vue'
import {canReviseSalesDraft, salesAmountSummary, shipmentDraftIssue, newSalesFilters, matchesSalesFilters} from '../src/renderer/src/utils/sales-documents.ts'
import {useSalesDraftEditor} from '../src/renderer/src/composables/use-sales-draft-editor.ts'
import {createSalesActions} from '../src/renderer/src/store/modules/sales-actions.ts'
import {initializeSessionState} from '../src/renderer/src/store/session-state.ts'
import {callBackend} from '../src/main/backend.ts'

test('销售金额与服务端分位一致，未填写不当作零价，赠品提示不禁止保存',()=>{
  assert.deepEqual(salesAmountSummary([{quantity:'2',unit_price:'0.335'},{quantity:'1',unit_price:'0'}]),{total:'0.67',zeroCount:1})
  assert.equal(salesAmountSummary([{quantity:'1',unit_price:''}]).total,null)
  assert.equal(salesAmountSummary([{quantity:'1000000',unit_price:'1000000000'}]).total,'1000000000000000.00')
})

test('修订只对服务端允许的草稿开放，未升级服务和审批中的过期快照均禁用',()=>{
  const row={id:1,status:'draft',draft_version:0,draft_edit_block_reason:''}
  assert.equal(canReviseSalesDraft(row),true)
  for(const item of [{...row,status:'posted'},{...row,draft_version:undefined},{...row,draft_edit_block_reason:'售后生成'},
    {...row,approval:{status:'approved'}},{...row,approval:{status:'submitted'}}])assert.equal(canReviseSalesDraft(item),false)
  assert.equal(canReviseSalesDraft({...row,approval:{status:'rejected'}}),true)
})

test('修订与跨页开单使用独立副本，关闭后恢复原新建草稿',()=>{
  const scope=effectScope()
  const draft=ref({reference:'未保存的新单',lines:[{quantity:'3'}]})
  scope.run(()=>{
    const editor=useSalesDraftEditor(draft)
    assert.equal(editor.beginEdit({id:2,status:'draft',draft_version:1,draft_edit_block_reason:''},
      {reference:'原单',lines:[{quantity:'1'}]}),true)
    editor.form.value.lines[0].quantity='2'
    assert.equal(draft.value.lines[0].quantity,'3')
    editor.open.value=false
    assert.equal(editor.target.value,null)
    assert.equal(editor.form.value.reference,'未保存的新单')
    editor.beginCreate({reference:'从订单开单',lines:[{quantity:'5'}]})
    assert.equal(draft.value.reference,'未保存的新单')
    editor.open.value=false
    assert.equal(editor.form.value.lines[0].quantity,'3')
  })
  scope.stop()
})

test('出库仅允许订单物料、剩余量和非重复明细，缺货可先保存草稿',()=>{
  const order={status:'confirmed',lines:[{material_id:1,remaining_quantity:'2.125',material_name:'产品',unit:'件'}]}
  assert.equal(shipmentDraftIssue(order,[{material_id:1,quantity:'2.125'}]),'')
  assert.match(shipmentDraftIssue(order,[{material_id:1,quantity:'2.126'}]),/订单剩余/)
  assert.match(shipmentDraftIssue(order,[{material_id:2,quantity:'1'}]),/该订单/)
  assert.match(shipmentDraftIssue(order,[{material_id:1,quantity:'1'},{material_id:1,quantity:'1'}]),/重复/)
  assert.match(shipmentDraftIssue({...order,status:'shipped'},[{material_id:1,quantity:'1'}]),/可出库状态/)
})

test('销售筛选区分审批、执行和冲销，日期按显示时区处理',()=>{
  const original=process.env.TZ;process.env.TZ='Asia/Shanghai'
  try {
    const row={status:'posted',created_at:'2026-10-20 23:30:00',reversal_id:1}
    assert.equal(matchesSalesFilters(row,2,{...newSalesFilters(),status:'reversed',customer:2,from:'2026-10-21',to:'2026-10-21'}),true)
    // 服务端时间带 T 但未带时区时仍为 UTC，与页面 localTime 保持一致。
    assert.equal(matchesSalesFilters({...row,created_at:'2026-10-20T23:30:00'},2,
      {...newSalesFilters(),from:'2026-10-21',to:'2026-10-21'}),true)
    assert.equal(matchesSalesFilters(row,2,{...newSalesFilters(),status:'posted'}),false)
    assert.equal(matchesSalesFilters(row,2,{...newSalesFilters(),customer:3}),false)
    assert.equal(matchesSalesFilters({...row,status:'draft',reversal_id:null,approval:{status:'approved'}},2,
      {...newSalesFilters(),status:'approved'}),true)
  } finally {if(original===undefined)delete process.env.TZ;else process.env.TZ=original}
})

test('修订 IPC 固定路径并去掉额外字段，拒绝无效版本和任意历史类型',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  const sent=[]
  globalThis.fetch=async(url,options)=>{
    if(new URL(url).pathname.endsWith('/login'))return new Response(JSON.stringify({token:'test',user:{id:1}}),{status:200})
    sent.push({path:new URL(url).pathname,method:options.method,body:options.body?JSON.parse(options.body):undefined})
    return new Response(JSON.stringify({id:1}),{status:200})
  }
  await callBackend('login',{})
  const body={orderId:1,customer_id:2,reference:'修订',expected_version:0,revision_reason:' 核对 ',
    hidden:'不能提交',lines:[{material_id:3,quantity:'1',unit_price:'2',warranty_days:null,warranty_basis:'',hidden:true}]}
  await callBackend('reviseSalesOrder',body)
  assert.equal(sent[0].method,'PUT');assert.equal(sent[0].path,'/api/v1/sales-orders/1')
  assert.equal(sent[0].body.revision_reason,'核对');assert.equal(sent[0].body.hidden,undefined)
  assert.equal(sent[0].body.lines[0].hidden,undefined)
  await assert.rejects(callBackend('reviseSalesOrder',{...body,expected_version:-1}),/版本/)
  await assert.rejects(callBackend('salesDraftChanges',{documentType:'../../users',documentId:1}),/类型/)
  await callBackend('reviseShipment',{shipmentId:4,sales_order_id:1,warehouse_id:1,reference:'',expected_version:0,revision_reason:'调整',
    lines:[{material_id:3,quantity:'1',hidden:true}]})
  assert.deepEqual(sent[1].body.lines,[{material_id:3,quantity:'1'}])
  await callBackend('reviseSalesReturn',{returnId:5,shipment_id:4,warehouse_id:1,reason:'实物退回',expected_version:0,revision_reason:'调整',
    lines:[{shipment_line_id:8,quantity:'1',hidden:true}]})
  assert.equal(sent[2].path,'/api/v1/sales-returns/5')
})

test('修订写入成功但刷新失败仍返回成功，换实例后的读取不泄露旧历史',async t=>{
  const original=globalThis.window;t.after(()=>{globalThis.window=original})
  const scope=effectScope();t.after(()=>scope.stop())
  const state={server:ref({id:'a',fingerprint:'a'}),user:ref({id:1,roles:['admin'],permissions:['sales.view','sales_order.create']}),
    connectionLost:ref(false),busy:ref(false),error:ref(''),notice:ref(''),salesForm:ref({reference:'原新单',lines:[]})}
  let finish
  globalThis.window={nexora:{callApi:async action=>action==='salesDraftChanges'?await new Promise(resolve=>{finish=resolve}):{id:1}}}
  let actions
  scope.run(()=>{
    initializeSessionState(state)
    actions=createSalesActions(state,async(action)=>{await action();state.error.value='刷新失败'})
  })
  assert.equal(await actions.reviseSalesDraft('reviseSalesOrder',{}),true)
  assert.equal(state.salesForm.value.reference,'原新单')
  const loading=actions.loadSalesDraftChanges('SalesOrder',1)
  state.server.value={id:'b',fingerprint:'b'}
  finish([{id:9}])
  await assert.rejects(loading,/会话已变化/)
})

test('终止交付 IPC 核对逐行实绩并只发送固定字段',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  let sent
  globalThis.fetch=async(url,options)=>{
    if(new URL(url).pathname.endsWith('/login'))return new Response(JSON.stringify({token:'test',user:{id:1}}),{status:200})
    sent={path:new URL(url).pathname,body:JSON.parse(options.body)}
    return new Response(JSON.stringify({status:'closed'}),{status:200})
  }
  await callBackend('login',{})
  const input={orderId:9,reason:' 客户同意 ',expected_lines:[{line_id:4,shipped_quantity:'1.250',hidden:true}],hidden:true}
  await callBackend('closeSalesOrder',input)
  assert.deepEqual(sent,{path:'/api/v1/sales-orders/9/close',body:{reason:'客户同意',expected_lines:[{line_id:4,shipped_quantity:'1.250'}]}})
  await assert.rejects(callBackend('closeSalesOrder',{...input,reason:' '}),/终止原因/)
  await assert.rejects(callBackend('closeSalesOrder',{...input,expected_lines:[{line_id:4,shipped_quantity:'NaN'}]}),/实绩/)
  await assert.rejects(callBackend('closeSalesOrder',{...input,expected_lines:[...input.expected_lines,...input.expected_lines]}),/重复/)
})

test('终止成功与刷新失败分开，权限撤回后不能继续提交',async t=>{
  const original=globalThis.window;t.after(()=>{globalThis.window=original})
  const scope=effectScope();t.after(()=>scope.stop())
  const state={server:ref({id:'a',fingerprint:'a'}),user:ref({id:1,roles:['admin'],permissions:['sales.view','sales_order.cancel']}),
    connectionLost:ref(false),busy:ref(false),error:ref(''),notice:ref('')}
  let calls=0,actions
  globalThis.window={nexora:{callApi:async()=>{calls++;return {status:'closed'}}}}
  scope.run(()=>{initializeSessionState(state);actions=createSalesActions(state,async action=>{await action();state.error.value='刷新失败'})})
  assert.equal(await actions.closeSalesOrder({orderId:1,reason:'客户同意',expected_lines:[]}),true)
  state.user.value.permissions=[]
  assert.equal(await actions.closeSalesOrder({orderId:1,reason:'客户同意',expected_lines:[]}),false)
  assert.equal(calls,1)
  assert.equal(matchesSalesFilters({status:'closed',created_at:'2026-10-21'},1,{...newSalesFilters(),status:'closed'}),true)
})
