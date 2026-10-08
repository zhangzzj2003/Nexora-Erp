import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createSubledgerActions } from '../src/renderer/src/store/modules/subledger-actions.ts'
import { callBackend } from '../src/main/backend.ts'
import { subledgerActions, subledgerDraftError } from '../src/renderer/src/views/workspace/finance/subledger-display.ts'
import { canVisitRoute, routeByKey } from '../src/renderer/src/router/workspace-routes.ts'

const permissions = ['subledger_opening.view','subledger_opening.create','subledger_opening.submit','finance.record','finance.reverse']
const options = { accounts:[],auxiliary_items:[],auxiliary_policies:[],opening_balance:{ id:1,version:4,status:'confirmed' } }
const input = { reference:'IMPORT',opening_balance_id:1,opening_version:4,control_accounts:[{kind:'receivable',account_id:3}],
  lines:[{kind:'receivable',party_id:5,account_id:3,document_reference:'OLD',document_date:'2025-12-01',debit:'100.10',credit:'0.00',auxiliary:[{kind:'project',id:7}]}],note:'原始清单',reason:'已核对' }
const deferred = () => { let resolve,reject; const promise = new Promise((yes,no) => {resolve=yes;reject=no}); return {promise,resolve,reject} }

test('分户表单拦截错误日期、重复原单及双边金额，不以浮点数汇总财务金额', () => {
  assert.equal(subledgerDraftError(input, '2026-01-01'), '')
  for (const edit of [{document_date:'2026-01-01'}, {document_date:'2025-02-30'}, {party_id:0},
    {debit:'1e2'}, {debit:'0'}, {credit:'20'}, {debit:'1.005'}, {account_id:99}]) {
    assert.ok(subledgerDraftError({...input,lines:[{...input.lines[0],...edit}]}, '2026-01-01'))
  }
  assert.match(subledgerDraftError({...input,lines:[...input.lines,{...input.lines[0],document_reference:' OLD '}]}, '2026-01-01'), /不能重复/)
  assert.equal(subledgerDraftError({...input,lines:[{...input.lines[0],debit:'0.00',credit:'20.11'}]}, '2026-01-01'), '')
  assert.equal(subledgerDraftError({...input,lines:[]}, '2026-01-01'), '')
  assert.ok(subledgerDraftError({...input,control_accounts:[]}, '2026-01-01'))
})

test('分户页面独立查看授权，参与编制者不能看到审核操作', () => {
  assert.equal(canVisitRoute(routeByKey('subledgerOpenings'), ['subledger_opening.view']), true)
  assert.equal(canVisitRoute(routeByKey('subledgerOpenings'), ['finance.view','journal.view']), false)
  const item={status:'submitted',author_ids:[1,2]}
  assert.deepEqual(subledgerActions(item,['subledger_opening.review'],1), [])
  assert.deepEqual(subledgerActions(item,['subledger_opening.review'],3), [])
  assert.deepEqual(subledgerActions({...item,status:'confirmed',reversal_approval:{status:'approved'}},['subledger_opening.cancel','subledger_opening.reverse'],3), ['reverse'])
  assert.deepEqual(subledgerActions({...item,status:'cancelled'},['subledger_opening.reverse'],3), [])
})
function fixture(t,callApi,perform=action=>action()) {
  const old=globalThis.window;t.after(()=>{globalThis.window=old})
  globalThis.window={nexora:{callApi}}
  const state=createAppState();state.user.value={id:1,permissions};state.subledgerQuery.value={to_date:'2026-10-01',kind:null,party_id:null}
  return {state,actions:createSubledgerActions(state,perform)}
}

test('分户 IPC 使用固定地址并剔除客户端快照、确认状态、期初金额和路径片段',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old})
  const requests=[]
  globalThis.fetch=async(url,config)=>{
    requests.push({path:new URL(url).pathname,...config,body:config.body?JSON.parse(config.body):null})
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:{}),{status:200,headers:{'Content-Type':'application/json'}})
  }
  await callBackend('login',{});requests.length=0
  await callBackend('createSubledgerOpening',{...input,status:'confirmed',effective_date:'2099-01-01',evidence:{matched:true},
    lines:input.lines.map(row=>({...row,party_name:'伪造姓名',opening_amount:'0',auxiliary:[{kind:'project',id:7,code:'FAKE',name:'伪造项目'}]}))})
  assert.equal(requests[0].path,'/api/v1/finance/subledger-openings');assert.deepEqual(requests[0].body,input)
  await callBackend('createSubledgerPayment',{line_id:9,action:'settlement',amount:'1',reference:'BANK',reason:'回单',kind:'payable',party_id:99,created_at:'1999-01-01'})
  assert.equal(requests[1].path,'/api/v1/finance/subledger-openings/lines/9/payments')
  assert.deepEqual(requests[1].body,{action:'settlement',amount:'1',reference:'BANK',reason:'回单'})
  for(const id of ['1/../../roles',true,0,-1,1.2]) await assert.rejects(callBackend('subledgerChanges',{id}),/编号无效/)
  await assert.rejects(callBackend('changeSubledgerStatus',{id:1,version:1,action:'post',reason:'绕开独立审核'}),/不允许/)
  await assert.rejects(callBackend('createSubledgerOpening',{...input,lines:null}),/明细/)
  assert.equal(requests.length,2)
})

test('筛选改变后迟到金额失效，CSV 只导出当前有效快照',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  const run=actions.querySubledger();state.subledgerQuery.value.kind='payable'
  pending.resolve({csv:'old-money'});assert.equal(await run,false);assert.equal(state.subledgerReport.value,null)
  let exported=0;globalThis.window.nexora.saveReportCsv=async()=>{exported++;return true}
  await actions.exportSubledger();assert.equal(exported,0)
  globalThis.window.nexora.callApi=async()=>({to_date:'2026-10-01',csv:'current'})
  assert.equal(await actions.querySubledger(),true)
  await actions.exportSubledger();assert.equal(exported,1)
})

test('换号与撤权清除旧账户金额、审计及编辑草稿，迟到写入不能清空新账号输入',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.subledgerForm.value={...input,id:null,version:1}
  const run=actions.saveSubledger()
  state.user.value={id:2,permissions};state.subledgerForm.value={...input,id:null,version:1,reference:'新账号未保存'}
  pending.resolve({id:9});assert.equal(await run,false);assert.equal(state.subledgerForm.value.reference,'新账号未保存')
  state.subledgerReport.value={csv:'秘密金额'};state.subledgerChanges.value=[{id:1}]
  state.user.value={id:2,permissions:[]}
  assert.equal(state.subledgerReport.value,null);assert.deepEqual(state.subledgerChanges.value,[]);assert.deepEqual(state.subledgerForm.value.lines,[])
})

test('断线与恢复保留未保存历史单据，选项和金额读取均失效',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  state.subledgerForm.value={...input,id:null,version:1};state.subledgerOptions.value=options
  const edit=actions.editSubledger();state.connectionLost.value=true;state.connectionLost.value=false
  pending.resolve({...options,opening_balance:{id:99,version:8}})
  assert.equal(await edit,false);assert.equal(state.subledgerForm.value.reference,'IMPORT');assert.equal(state.subledgerOptions.value.opening_balance.id,1)
  assert.deepEqual(state.subledgerForm.value.lines,input.lines)
})

test('保存使用普通数据且失败保留输入和版本，成功刷新后清理已保存草稿',async t=>{
  const calls=[];let fail=true
  const {state,actions}=fixture(t,async(action,payload)=>{
    calls.push([action,payload])
    if(action==='updateSubledgerOpening'){structuredClone(payload);if(fail)throw Error('版本已变化')}
    if(action==='subledgerOptions')return options
    return []
  },async run=>{try{await run()}catch{}})
  state.subledgerForm.value={...input,id:2,version:6,lines:input.lines.map(row=>({...row,_X_ROW_KEY:'控件行标记'}))}
  assert.equal(await actions.saveSubledger(),false);assert.equal(state.subledgerForm.value.version,6)
  assert.equal(state.subledgerForm.value.reference,'IMPORT');assert.deepEqual(calls[0][1],{...input,id:2,version:6})
  fail=false;assert.equal(await actions.saveSubledger(),true);assert.deepEqual(state.subledgerForm.value.lines,[])
})

test('详情关闭或切换后迟到审计不会重新出现，已撤销方案使用固定证据',async t=>{
  const pending=deferred();const {state,actions}=fixture(t,()=>pending.promise)
  const run=actions.loadSubledgerDetail({id:1,status:'confirmed',evidence:{matched:true}})
  actions.clearSubledgerDetail();pending.resolve([{id:1}]);assert.equal(await run,false)
  assert.deepEqual(state.subledgerChanges.value,[]);assert.equal(state.subledgerCheck.value,null)
  const called=[];globalThis.window.nexora.callApi=async(action)=>{called.push(action);return [{id:2}]}
  assert.equal(await actions.loadSubledgerDetail({id:1,status:'cancelled',evidence:null}),true)
  assert.deepEqual(called,['subledgerChanges']);assert.equal(state.subledgerCheck.value,null)
})

test('只读用户加载方案和资金历史，无权读取建单选项或写入',async t=>{
  const calls=[];const {state,actions}=fixture(t,async(action)=>{calls.push(action);return []})
  state.user.value={id:1,permissions:['subledger_opening.view']}
  assert.equal(await actions.loadSubledger(),true);assert.deepEqual(calls,['subledgerOpenings','subledgerPayments','subledgerSettlements'])
  assert.equal(state.subledgerOptions.value,null)
  assert.equal(await actions.saveSubledger(),false);assert.equal(await actions.createSubledgerPayment({line_id:1}),false)
  assert.equal(calls.length,3)
})

// 排队期间切换服务端，原方案的批准不能用于新服务端上的同号记录。
test('分户旧审核及未批准启用被阻止，排队执行不能跨服务端',async t=>{
  const pending=deferred(),calls=[]
  const {state,actions}=fixture(t,async(...input)=>{calls.push(input)},async fn=>{
    await pending.promise;try{await fn()}catch(e){state.error.value=e.message}
  })
  state.user.value={id:1,permissions:[...permissions,'subledger_opening.confirm']}
  state.server.value={id:'source',fingerprint:'source-ca'}
  const row={id:1,version:3}
  assert.equal(await actions.changeSubledgerStatus(row,'submit','旧审核'),false)
  assert.equal(await actions.changeSubledgerStatus(row,'confirm','提前启用'),false)
  const run=actions.changeSubledgerStatus({...row,approval:{status:'approved'}},'confirm','逐组合核对')
  state.server.value={id:'destination',fingerprint:'other-ca'};pending.resolve()
  assert.equal(await run,false);assert.equal(calls.length,0)
  assert.match(state.error.value,/会话或连接已变化/)
})

// 资金草稿执行继续在真正发送前复核实例与权限，不能沿用旧服务端批准。
test('分户资金批准门槛与排队切换服务端使执行失效',async t=>{
  const pending=deferred(),calls=[]
  const {state,actions}=fixture(t,async(...args)=>{calls.push(args)},async fn=>{await pending.promise;try{await fn()}catch(e){state.error.value=e.message}})
  state.server.value={id:'original',fingerprint:'original-ca'}
  const row={id:1,version:1,status:'draft',reverses_id:null}
  assert.equal(await actions.changeSubledgerPaymentStatus(row,'post','提前执行'),false)
  assert.equal(await actions.changeSubledgerPaymentStatus({...row,approval:{status:'approved'}},'cancel','绕过撤回'),false)
  const run=actions.changeSubledgerPaymentStatus({...row,approval:{status:'approved'}},'post','核对执行')
  state.server.value={id:'next',fingerprint:'next-ca'};pending.resolve()
  assert.equal(await run,false);assert.equal(calls.length,0);assert.match(state.error.value,/会话或连接已变化/)
})

// 在另一客户端审批后，通用刷新同步资金列表和原截止日余额，不能保留旧可执行状态。
test('分户审批刷新同步资金列表并恢复同截止日核对',async t=>{
  const calls=[]
  const {state,actions}=fixture(t,async action=>{calls.push(action);if(action==='subledgerPayments')return [{id:1,status:'draft',approval:{status:'approved'}}];if(action==='querySubledger')return {to_date:'2026-10-01',csv:'当前快照'};return []})
  state.subledgerReport.value={to_date:'2026-10-01',csv:'旧快照'}
  await actions.refreshSubledgerApproval()
  assert.deepEqual(calls,['subledgerOpenings','subledgerPayments','subledgerOptions','subledgerSettlements','querySubledger'])
  assert.equal(state.subledgerPayments.value[0].approval.status,'approved');assert.equal(state.subledgerReport.value.csv,'当前快照')
})
