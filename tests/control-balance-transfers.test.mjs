import assert from 'node:assert/strict'
import {test} from 'node:test'
import {controlTransferBody,fundsScopeBody,validateControlBalanceResult} from '../src/shared/control-balance-validation.ts'
import {controlTransferLimit,controlChoice,controlCombinationKey} from '../src/renderer/src/views/workspace/finance/control-balance-display.ts'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createControlBalanceActions} from '../src/renderer/src/store/modules/control-balance-actions.ts'
import {callBackend} from '../src/main/backend.ts'

const sha='a'.repeat(64)
const source=()=>({kind:'receivable',source_type:'historical',source_id:1,party_id:2,party_name:'客户甲',reference:'OLD-1',account_id:4,
  auxiliary:[{kind:'customer',id:2,name:'客户甲'},{kind:'project',id:3,name:'项目甲'}],outstanding_amount:'-20.01',fingerprint:sha,evidence:[],blockers:[]})
const target=()=>({...source(),source_type:'order',source_id:6,account_id:5,outstanding_amount:'12.02'})
const record=()=>({id:1,document_no:'CBT-20261009-000001',kind:'receivable',operation:'allocate',party_id:2,currency:'CNY',business_date:'2026-10-09',
  amount:'2.00',from_delta:'2.00',from_scope:source(),to_scope:target(),evidence:{source:source(),target:target()},reference:'R',reason:'核对原单组合',
  status:'draft',version:1,reverses_id:null,reversal_id:null,journal_id:null,journal_status:null})
const input=()=>({kind:'receivable',operation:'allocate',business_date:'2026-10-09',from_scope:controlChoice(source()),to_scope:controlChoice(target()),amount:'2',reference:' R ',reason:' 核对组合 '})
const origin=()=>({...source(),groups:[source()]})
const options=()=>({currency:'CNY',origins:[origin()],accounts:[{id:4},{id:5}],control_accounts:[{kind:'receivable',account_id:4},{kind:'receivable',account_id:5}],auxiliary_items:[],auxiliary_policies:[]})
const approval=(status='draft',version=0)=>({document_type:'ControlBalanceTransfer',document_id:1,intent:'execute',version,status,generation:0,current_step:0,
  summary:[],business_status:'draft',reversal_reason:'',content_matches:true,steps:[],policy_version:null,submitted_by:null,submitted_at:null,executed_by:null,executed_at:null,
  can_submit:true,can_review:false,can_withdraw:false,events:[]})

test('转账精确额度限定实际往来、不同原单与完整组合，重分类保留原单总额',()=>{
  assert.equal(controlTransferLimit(source(),target(),'allocate'),1202n)
  for(const change of [{party_id:8},{kind:'payable'},{blockers:['待过账']},{outstanding_amount:'-1.00'},
    {source_type:'historical',source_id:1},{account_id:4}]) assert.equal(controlTransferLimit(source(),{...target(),...change},'allocate'),0n)
  assert.equal(controlTransferLimit({...source(),outstanding_amount:'9999999999999.99'},null,'reclassify'),999999999999999n)
  assert.equal(controlCombinationKey(source()),controlCombinationKey({...source(),auxiliary:[...source().auxiliary].reverse()}))
})

test('转账与资金写入深拷贝白名单，拒绝无效日期、指纹与重复辅助',()=>{
  const value=input(),body=controlTransferBody({...value,status:'executed',party_id:999})
  assert.equal(body.reference,'R');assert.equal(body.reason,'核对组合');assert.equal(body.status,undefined)
  value.from_scope.auxiliary[0].id=999;assert.notEqual(body.from_scope.auxiliary[0].id,999)
  const fixed=fundsScopeBody({...source(),status:'executed'});assert.deepEqual(Object.keys(fixed).sort(),['account_id','auxiliary','fingerprint'])
  for(const patch of [{amount:'0.001'},{amount:'0'},{amount:'1e3'},{amount:2},{business_date:'2026-02-30'},
    {reason:' '},{from_scope:{...input().from_scope,fingerprint:null}},{to_scope:{...input().to_scope,fingerprint:null}},
    {from_scope:{...input().from_scope,auxiliary:[{kind:'customer',id:2},{kind:'customer',id:2}]}}]) assert.throws(()=>controlTransferBody({...input(),...patch}))
  assert.doesNotThrow(()=>controlTransferBody({...input(),operation:'reclassify',to_scope:{...input().to_scope,fingerprint:null}}))
})

test('转账响应拒绝错原单、组合与金额，生效须具备真实已过账凭证',()=>{
  validateControlBalanceResult('controlBalanceTransfers',[record()]);validateControlBalanceResult('controlBalanceOptions',options())
  for(const patch of [{currency:'USD'},{status:'approved'},{party_id:8},{from_delta:'3.00'},{amount:'0.00'},
    {status:'executed',journal_id:1,journal_status:'approved'},{evidence:{source:{...source(),account_id:7},target:target()}},
    {evidence:{source:{...source(),evidence:[{type:'journal',journal_id:1}]},target:target()}}]) assert.throws(()=>validateControlBalanceResult('controlBalanceDetail',{...record(),...patch}))
  for(const patch of [{outstanding_amount:'5.00'},{groups:[source(),source()]},{groups:[{...source(),party_id:8}]}])
    assert.throws(()=>validateControlBalanceResult('controlBalanceFundsOptions',{currency:'CNY',required:true,origin:{...origin(),...patch}}))
  assert.throws(()=>validateControlBalanceResult('controlBalanceOptions',{...options(),control_accounts:[{kind:'payable',account_id:77}]}))
  assert.throws(()=>validateControlBalanceResult('controlBalanceFundsOptions',{currency:'CNY',required:true,origin:null}))
})

test('生成凭证响应的两条真实分录与固定组合及借贷方向一致',()=>{
  const row={...record(),journal_id:9},line=(scope,debit,credit)=>({account_id:scope.account_id,auxiliary:scope.auxiliary,debit,credit})
  const journal={id:9,currency:'CNY',status:'draft',journal_date:row.business_date,lines:[line(row.from_scope,'2.00','0.00'),line(row.to_scope,'0.00','2.00')]}
  validateControlBalanceResult('generateControlBalanceJournal',{transfer:row,journal})
  for(const patch of [{id:8},{currency:'USD'},{journal_date:'2026-10-08'},{lines:[]},
    {lines:[{...journal.lines[0],account_id:5},journal.lines[1]]},{lines:[{...journal.lines[0],debit:'3.00'},journal.lines[1]]}])
    assert.throws(()=>validateControlBalanceResult('generateControlBalanceJournal',{transfer:row,journal:{...journal,...patch}}))
})

test('转账 IPC 固定地址、执行版本及白名单，资金原单查询不能注入路径',async t=>{
  const old=globalThis.fetch;t.after(()=>{globalThis.fetch=old});const requests=[]
  globalThis.fetch=async(url,config)=>{requests.push({path:new URL(url).pathname,query:new URL(url).search,body:config.body?JSON.parse(config.body):null});
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')?{token:'test',user:{id:1}}:
      new URL(url).pathname.endsWith('/funds-options')?{currency:'CNY',required:false,origin:null}:{...record(),approval:approval()}),{status:200,headers:{'Content-Type':'application/json'}})}
  await callBackend('login',{});requests.length=0
  await callBackend('createControlBalanceTransfer',{...input(),status:'executed',party_id:999})
  assert.deepEqual(requests[0],{path:'/api/v1/finance/control-transfers',query:'',body:controlTransferBody(input())})
  await callBackend('cancelControlBalanceTransfer',{id:7,version:2,reason:' 核对取消 ',cancelled_by:999})
  assert.deepEqual(requests[1],{path:'/api/v1/finance/control-transfers/7/cancel',query:'',body:{version:2,reason:'核对取消'}})
  await callBackend('controlBalanceFundsOptions',{kind:'receivable',source_type:'order',source_id:8})
  assert.equal(requests[2].query,'?kind=receivable&source_type=order&source_id=8')
  for(const patch of [{id:true},{id:'../users'},{version:0},{reason:' '}]) await assert.rejects(callBackend('cancelControlBalanceTransfer',{id:7,version:2,reason:'核对',...patch}))
  await assert.rejects(callBackend('controlBalanceFundsOptions',{kind:'../users',source_type:'order',source_id:8}))
  assert.equal(requests.length,3)
})

function setup(t,permissions,api,perform=async fn=>{try{await fn()}catch{}},refresh=async()=>{}) {
  const old=globalThis.window;t.after(()=>{globalThis.window=old});globalThis.window={nexora:{callApi:api}}
  const state=createAppState();state.user.value={id:1,roles:['finance'],permissions};state.server.value={id:'one',fingerprint:'ca-one'}
  const actions=createControlBalanceActions(state,perform,refresh);return {state,actions}
}
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return {promise,resolve}}

test('截止日加载状态由当前请求与会话持有，旧返回、断线与失败不会误清新查询',async t=>{
  const gates=[],{state,actions}=setup(t,['control_transfer.view'],async()=>{
    const gate=deferred();gates.push(gate);const result=await gate.promise
    if(result instanceof Error)throw result
    return result
  })
  const first=actions.queryControlBalances('2026-10-08'),second=actions.queryControlBalances('2026-10-09')
  assert.equal(state.controlBalanceReportLoading.value,true)
  gates[0].resolve({currency:'CNY',to_date:'2026-10-08',origins:[]});assert.equal(await first,false)
  assert.equal(state.controlBalanceReportLoading.value,true);assert.equal(state.controlBalanceReport.value,null)
  gates[1].resolve({currency:'CNY',to_date:'2026-10-09',origins:[]});assert.equal(await second,true)
  assert.equal(state.controlBalanceReportLoading.value,false);assert.equal(state.controlBalanceReport.value.to_date,'2026-10-09')
  const obsolete=actions.queryControlBalances('2026-10-08');state.connectionLost.value=true
  assert.equal(state.controlBalanceReportLoading.value,false);state.connectionLost.value=false
  const current=actions.queryControlBalances('2026-10-09');gates[2].resolve({currency:'CNY',to_date:'2026-10-08',origins:[]})
  assert.equal(await obsolete,false);assert.equal(state.controlBalanceReportLoading.value,true)
  gates[3].resolve(Error('截止日来源查询失败'));assert.equal(await current,false)
  assert.equal(state.controlBalanceReportLoading.value,false);assert.equal(state.controlBalanceReport.value,null)
  assert.match(state.controlBalanceError.value,/截止日来源查询失败/)
})

test('晚到读取、切换证书、撤权与断线不能覆盖新会话的转账详情或余额',async t=>{
  const gate=deferred(),{state,actions}=setup(t,['control_transfer.view','journal.view'],async op=>{await gate.promise;return op==='controlBalanceOptions'?options():op==='controlBalanceTransfers'?[record()]:op==='controlBalanceDetail'?record():[]})
  const reads=[actions.loadControlBalances(),actions.loadControlBalanceDetail(1),actions.queryControlBalances('2026-10-09'),actions.loadControlBalanceJournal(9)]
  state.server.value={id:'one',fingerprint:'new-cert'};gate.resolve();assert.deepEqual(await Promise.all(reads),[false,false,false,false])
  assert.equal(state.controlBalanceDetail.value,null);assert.equal(state.controlBalanceReport.value,null);assert.equal(state.controlBalanceJournal.value,null)
  state.controlBalanceTransfers.value=[record()];state.user.value.permissions=['journal.view'];assert.deepEqual(state.controlBalanceTransfers.value,[])
  assert.equal(await actions.loadControlBalances(),false)
  state.user.value.permissions=['control_transfer.view'];state.controlBalanceTransfers.value=[record()];state.connectionLost.value=true
  assert.deepEqual(state.controlBalanceTransfers.value,[]);assert.equal(state.controlBalanceLoading.value,false)
})

test('排队过账需要当前双重批准及组合权限；凭证审批版本变化不会发送',async t=>{
  const gate=deferred(),calls=[],{state,actions}=setup(t,['control_transfer.view','control_transfer.post','journal.view','journal.post'],async(...args)=>{calls.push(args);return []},async fn=>{await gate.promise;try{await fn()}catch{}})
  const row={...record(),journal_id:9,approval:{status:'approved',version:3}},journal={id:9,status:'approved',version:2,approval:{status:'approved',version:3}}
  state.controlBalanceTransfers.value=[row];state.controlBalanceJournal.value=journal
  assert.equal(await actions.postControlBalanceJournal({...row,approval:{status:'submitted',version:3}},journal,'核对'),false)
  const pending=actions.postControlBalanceJournal(row,journal,'核对过账');state.controlBalanceJournal.value={...journal,approval:{status:'approved',version:4}};gate.resolve()
  assert.equal(await pending,false);assert.deepEqual(calls,[])
})

test('资金组合读取仅依赖资金权限；跨会话返回会报错，取消关联凭证也需组合授权',async t=>{
  const gate=deferred(),calls=[],{state,actions}=setup(t,['finance.record','journal.cancel','journal.view','control_transfer.view'],async(...args)=>{calls.push(args);await gate.promise;return {currency:'CNY',required:false,origin:null}})
  const pending=actions.loadControlFundsOptions({kind:'receivable',source_type:'order',source_id:6});state.connectionLost.value=true;gate.resolve()
  await assert.rejects(pending,/会话已变化/);state.connectionLost.value=false
  const row={...record(),journal_id:9},journal={id:9,status:'draft',version:1,approval:{status:'draft',version:0}}
  state.controlBalanceTransfers.value=[row];state.controlBalanceJournal.value=journal
  assert.equal(await actions.cancelControlBalanceJournal(row,journal,'取消'),false);assert.equal(calls.length,1)
})
