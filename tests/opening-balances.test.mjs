import assert from 'node:assert/strict'
import { test } from 'node:test'
import { toRaw } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createOpeningBalanceActions } from '../src/renderer/src/store/modules/opening-balance-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { openingTotals } from '../src/renderer/src/views/workspace/finance/opening-display.ts'
import { canVisitRoute,routeByKey } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'
const permissions=['opening_balance.view','opening_balance.create','opening_balance.submit','opening_balance.confirm']
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return{promise,resolve}}
function setup(t){const old=globalThis.window;t.after(()=>{globalThis.window=old});const state=createAppState();state.user.value={id:1,permissions};return state}

test('期初合计精确到分，明确零余额可保存，重复科目不允许',()=>{
  assert.deepEqual(openingTotals([]),{debit:'0.00',credit:'0.00',balanced:true})
  const line=(account_id,debit,credit)=>({account_id,summary:'依据',debit,credit})
  assert.equal(openingTotals([line(1,'999999999999.99','0'),line(2,'0','999999999999.99')]).balanced,true)
  assert.equal(openingTotals([line(1,'1','0'),line(1,'0','1')]).balanced,false)
  for(const value of ['NaN','1e2','-1','0.001'])assert.equal(openingTotals([line(1,value,'0'),line(2,'0','1')]).balanced,false)
})
test('期初入口独立授权，IPC 固定动作、正编号与版本字段',async t=>{
  assert.equal(canVisitRoute(routeByKey('openingBalances'),['opening_balance.view']),true)
  assert.equal(canVisitRoute(routeByKey('openingBalances'),['journal.view']),false)
  const old=process.env.NEXORA_API_URL;t.after(()=>{if(old===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=old})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123';const calls=[]
  t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push([url.pathname,options.method,options.body]);return Response.json(url.pathname.endsWith('/login')?{token:'test',user:{id:1}}:[])})
  await callBackend('login',{})
  await callBackend('changeOpeningBalanceStatus',{id:7,version:3,action:'confirm',reason:'核对',status:'confirmed'})
  assert.deepEqual(calls.at(-1),['/api/v1/finance/opening-balances/7/confirm','POST',JSON.stringify({version:3,reason:'核对'})])
  await assert.rejects(callBackend('changeOpeningBalanceStatus',{id:7,action:'../users'}),/不允许的期初状态操作/)
  for(const action of ['updateOpeningBalance','openingBalanceChanges','changeOpeningBalanceStatus'])await assert.rejects(callBackend(action,{id:'../users',action:'submit'}),/记录编号无效/)
})
test('期初失败保留草稿，保存不传快照；状态携带原版本和原因',async t=>{
  const state=setup(t);const calls=[];let fail=true
  globalThis.window={nexora:{async callApi(action,input){calls.push([action,input===undefined?undefined:structuredClone(input)]);if(action==='openingBalanceOptions')return{accounts:[],period:{start_date:'2026-01-01'}};if(fail)throw Error('版本冲突')}}}
  const actions=createOpeningBalanceActions(state,async fn=>{try{await fn()}catch(e){state.error.value=e.message}})
  const item={id:7,version:2,reference:'OPEN',effective_date:'2026-01-01',note:'备注',lines:[{account_id:1,summary:'余额依据',debit:'1',credit:'0',account_name:'快照'}]}
  assert.equal(await actions.editOpeningBalance(item),true);state.openingBalanceForm.value.reason='更正'
  const before=structuredClone(toRaw(state.openingBalanceForm.value))
  assert.equal(await actions.saveOpeningBalance(),false);assert.deepEqual(state.openingBalanceForm.value,before)
  assert.deepEqual(calls.at(-1),['updateOpeningBalance',{id:7,version:2,reference:'OPEN',effective_date:'2026-01-01',note:'备注',reason:'更正',lines:[{account_id:1,summary:'余额依据',debit:'1',credit:'0'}]}])
  fail=false;assert.equal(await actions.saveOpeningBalance(),true)
  assert.equal(await actions.changeOpeningBalanceStatus(item,'confirm','核对'),true)
  assert.deepEqual(calls.at(-1),['changeOpeningBalanceStatus',{id:7,version:2,action:'confirm',reason:'核对'}])
})
test('撤权清除期初数据和表单，晚到的选项不可恢复；其他模块失败前已清理',async t=>{
  const state=setup(t);const pending=deferred()
  globalThis.window={nexora:{callApi(){return pending.promise}}}
  const actions=createOpeningBalanceActions(state,async fn=>fn());const loading=actions.editOpeningBalance()
  state.openingBalances.value=[{id:1}];state.openingBalanceForm.value.reference='私有草稿';state.user.value=null
  pending.resolve({accounts:[{id:1}],period:null});assert.equal(await loading,false)
  assert.deepEqual(state.openingBalances.value,[]);assert.equal(state.openingBalanceForm.value.reference,'');assert.deepEqual(state.openingBalanceOptions.value,{accounts:[],period:null})
  state.user.value={id:1,permissions};state.openingBalances.value=[{id:1}];state.openingBalanceOptions.value={accounts:[{id:1}],period:null}
  globalThis.window={nexora:{async callApi(action){if(action==='me')return{id:1,permissions:['inventory.view']};if(action==='menuIcons')throw Error('业务失败');return[]}}}
  await assert.rejects(createDataLoader(state,p=>state.user.value.permissions.includes(p),()=>{}).refreshData(),/业务失败/)
  assert.deepEqual(state.openingBalances.value,[]);assert.deepEqual(state.openingBalanceOptions.value,{accounts:[],period:null})
})
test('会话改变时旧保存不会清除新账号草稿，离线或撤权不得写入',async t=>{
  const state=setup(t);const pending=deferred();let calls=0
  globalThis.window={nexora:{callApi(){calls++;return pending.promise}}}
  const actions=createOpeningBalanceActions(state,async fn=>fn())
  const saved=actions.saveOpeningBalance();state.user.value={id:2,permissions};state.openingBalanceForm.value.reference='新草稿'
  pending.resolve({});assert.equal(await saved,false);assert.equal(state.openingBalanceForm.value.reference,'新草稿')
  state.connectionLost.value=true;assert.equal(await actions.saveOpeningBalance(),false);assert.equal(calls,1)
  state.connectionLost.value=false;state.user.value={id:2,permissions:[]};assert.equal(await actions.changeOpeningBalanceStatus({id:1,version:1},'confirm','越权'),false);assert.equal(calls,1)
})
