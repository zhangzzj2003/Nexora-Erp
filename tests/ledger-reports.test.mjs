import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createLedgerReportActions } from '../src/renderer/src/store/modules/ledger-report-actions.ts'
import { callBackend } from '../src/main/backend.ts'
import { canVisitRoute, routeByKey } from '../src/renderer/src/router/workspace-routes.ts'

const filters = {kind:'trial_balance',from_date:'2026-01-10',to_date:'2026-01-20',account_id:null}
const deferred = () => { let resolve; let reject; const promise = new Promise((a,b)=>{resolve=a;reject=b}); return {promise,resolve,reject} }
function setup(t) {
  const old = globalThis.window; t.after(()=>{globalThis.window=old})
  const state=createAppState(); state.user.value={id:1,permissions:['journal.view']}; state.ledgerReportQuery.value={...filters}
  return {state,actions:createLedgerReportActions(state)}
}

test('总账报表与凭证共用查看权限，IPC 固定路径且不传入额外查询字段',async t=>{
  assert.equal(canVisitRoute(routeByKey('ledgerReports'),['journal.view']),true)
  assert.equal(canVisitRoute(routeByKey('ledgerReports'),['finance.view']),false)
  const old=process.env.NEXORA_API_URL; t.after(()=>{if(old===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=old})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123';const calls=[]
  t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push([url.pathname,options.method,options.body]);return Response.json(url.pathname.endsWith('/login')?{token:'test',user:{id:1}}:[])})
  await callBackend('login',{})
  await callBackend('queryLedgerReport',{...filters,status:'draft',extra:'discard'})
  assert.deepEqual(calls.at(-1),['/api/v1/finance/ledger-reports/query','POST',JSON.stringify(filters)])
  await callBackend('journalDetail',{id:3}); assert.equal(calls.at(-1)[0],'/api/v1/finance/journals/3')
  await assert.rejects(callBackend('journalDetail',{id:'../users'}),/记录编号无效/)
})

test('条件变更使旧结果和过期响应失效，旧请求不能解除新请求加载状态',async t=>{
  const {state,actions}=setup(t);const pending=[deferred(),deferred()];let index=0;const inputs=[]
  globalThis.window={nexora:{callApi(action,input){inputs.push(structuredClone(input));return pending[index++].promise}}}
  state.ledgerReportResult.value={csv:'旧数据'}
  const first=actions.queryLedgerReport();assert.equal(state.ledgerReportResult.value,null)
  state.ledgerReportQuery.value.to_date='2026-01-31';const second=actions.queryLedgerReport()
  pending[0].resolve({csv:'过期'});await first
  assert.equal(state.ledgerReportResult.value,null);assert.equal(state.ledgerReportLoading.value,true)
  pending[1].resolve({csv:'新数据',filters:{...filters,to_date:'2026-01-31'}});await second
  assert.equal(state.ledgerReportResult.value.csv,'新数据');assert.equal(state.ledgerReportLoading.value,false)
  assert.deepEqual(inputs[0],{...filters,paged:true})
  state.ledgerReportQuery.value.kind='account_ledger';assert.equal(state.ledgerReportResult.value,null)
})

test('撤权和退出清除报表、选项、详情，晚到的响应不可恢复快照',async t=>{
  const {state,actions}=setup(t);const q=deferred(),o=deferred(),d=deferred()
  globalThis.window={nexora:{callApi(action){return action==='queryLedgerReport'?q.promise:action==='ledgerReportOptions'?o.promise:d.promise}}}
  state.ledgerReportResult.value={csv:'私有'};state.ledgerReportAccounts.value=[{id:1}];state.ledgerReportJournal.value={id:1}
  const pending=[actions.queryLedgerReport(),actions.loadLedgerReportOptions(),actions.openLedgerReportJournal(1)]
  state.user.value={id:1,permissions:[]}
  assert.equal(state.ledgerReportResult.value,null);assert.deepEqual(state.ledgerReportAccounts.value,[]);assert.equal(state.ledgerReportJournal.value,null)
  state.user.value={id:1,permissions:['journal.view']}
  q.resolve({csv:'不可恢复'});o.resolve([{id:2}]);d.resolve({id:2});await Promise.all(pending)
  assert.equal(state.ledgerReportResult.value,null);assert.deepEqual(state.ledgerReportAccounts.value,[]);assert.equal(state.ledgerReportJournal.value,null)
  state.ledgerReportResult.value={csv:'再次登录'};state.user.value=null
  assert.equal(state.ledgerReportResult.value,null)
})

test('关闭详情拒绝晚到记录，查询失败清除旧快照并能重试；导出保存当前服务端 CSV',async t=>{
  const {state,actions}=setup(t);const detail=deferred();const saved=[];let fail=true;let cancel=false
  const result={kind:'trial_balance',filters:{...filters},csv:'\ufeff服务端精确快照',rows:[]}
  globalThis.window={nexora:{async callApi(action){if(action==='journalDetail')return detail.promise;if(fail)throw Error('Error invoking remote method \'api\': Error: 日期无效');return result},async saveReportCsv(name,csv){saved.push([name,csv]);return !cancel}}}
  const open=actions.openLedgerReportJournal(1);actions.closeLedgerReportJournal();detail.resolve({id:1});await open
  assert.equal(state.ledgerReportJournal.value,null)
  state.ledgerReportResult.value=result;await actions.queryLedgerReport()
  assert.equal(state.ledgerReportError.value,'日期无效');assert.equal(state.ledgerReportResult.value,null)
  fail=false;await actions.queryLedgerReport();await actions.exportLedgerReport()
  assert.deepEqual(saved,[['trial_balance-2026-01-10-2026-01-20.csv',result.csv]])
  assert.equal(state.notice.value,'总账报表 CSV 已保存。')
  state.notice.value='';cancel=true;await actions.exportLedgerReport();assert.equal(state.notice.value,'')
  state.connectionLost.value=true;await actions.exportLedgerReport();assert.equal(saved.length,2)
})
