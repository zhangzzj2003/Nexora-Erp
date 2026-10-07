import assert from 'node:assert/strict'
import { test } from 'node:test'
import { toRaw } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createJournalActions } from '../src/renderer/src/store/modules/journal-actions.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'
import { journalTotals } from '../src/renderer/src/views/workspace/finance/journal-display.ts'
import { visibleRouteGroups } from '../src/renderer/src/router/workspace-routes.ts'
import { callBackend } from '../src/main/backend.ts'

test('凭证合计按整数分计算，非法输入和双边金额不可当作平衡', () => {
  const line = (debit, credit) => ({ account_id: 1, summary: '合计', debit, credit })
  assert.deepEqual(journalTotals([line('0.1','0'),line('0.2','0'),line('0','0.3')]), { debit: '0.30', credit: '0.30', balanced: true })
  for (const invalid of ['NaN','1e2','0.001','-1','1000000000000']) assert.equal(journalTotals([line(invalid,'0'),line('0','0.3')]).balanced, false)
  assert.equal(journalTotals([line('1','1'),line('0','0')]).balanced, false)
  assert.equal(journalTotals([line('999999999999.99','0'),line('0','999999999999.99')]).balanced, true)
})

test('凭证页面以独立查看权限登记', () => {
  assert.equal(visibleRouteGroups(['journal.view']).find(g => g.key==='finance').routes[0].key, 'journals')
  assert.equal(visibleRouteGroups(['journal.create']).some(g => g.routes.some(r => r.key==='journals')), false)
})

test('凭证编辑提交普通字段，冲突保留旧版本和草稿；状态及冲销携带打开时版本', async t => {
  const old=globalThis.window; t.after(()=>{globalThis.window=old})
  const state=createAppState(); const calls=[]; let fail=true
  globalThis.window={nexora:{async callApi(action,input){
    calls.push([action, input===undefined ? undefined : structuredClone(input)])
    if(action==='journalOptions')return {accounts:[],periods:[]}
    if(fail)throw Error('版本冲突')
  }}}
  const actions=createJournalActions(state,async fn=>{try{await fn()}catch(error){state.error.value=error.message}})
  const record={id:7,version:3,reference:'J001',journal_date:'2026-01-10',note:'备注',lines:[{id:9,account_id:1,summary:'现金',debit:'0.30',credit:'0.00',account_name:'不能传'}]}
  await actions.editJournal(record); state.journalForm.value.reason='更正'
  const before=structuredClone(toRaw(state.journalForm.value))
  assert.equal(await actions.saveJournal(),false); assert.deepEqual(state.journalForm.value,before)
  assert.deepEqual(calls.at(-1),['updateJournal',{id:7,version:3,reference:'J001',journal_date:'2026-01-10',note:'备注',reason:'更正',lines:[{account_id:1,summary:'现金',debit:'0.30',credit:'0.00'}]}])
  fail=false; assert.equal(await actions.saveJournal(),true); assert.equal(state.journalForm.value.id,null)
  assert.equal(await actions.changeJournalStatus(record,'submit','核对'),false)
  const approved={...record,approval:{status:'approved'}}
  await actions.changeJournalStatus(approved,'post','核对'); assert.deepEqual(calls.at(-1),['changeJournalStatus',{id:7,version:3,action:'post',reason:'核对'}])
  await actions.reverseJournal(record,'REV','2026-01-20','纠错'); assert.deepEqual(calls.at(-1),['reverseJournal',{id:7,version:3,reference:'REV',journal_date:'2026-01-20',reason:'纠错'}])
})

test('撤权时在其他业务请求失败前清除凭证及建单选项', async t => {
  const old=globalThis.window; t.after(()=>{globalThis.window=old})
  const state=createAppState();state.user.value={permissions:['journal.view','journal.create']};state.journals.value=[{id:1}];state.journalOptions.value={accounts:[{id:1}],periods:[{id:1}]}
  globalThis.window={nexora:{async callApi(action){if (action === 'documentNumbering') return { configured: true };
    if(action==='me')return {permissions:['inventory.view']}; if(action==='materials')throw Error('其他模块失败');return []}}}
  const loader=createDataLoader(state,p=>state.user.value.permissions.includes(p),()=>{})
  await assert.rejects(loader.refreshData(),/其他模块失败/)
  assert.deepEqual(state.journals.value,[]);assert.deepEqual(state.journalOptions.value,{accounts:[],periods:[]})
})

test('凭证 IPC 拒绝非法动作和路径，限制版本及冲销字段',async t=>{
  const old=process.env.NEXORA_API_URL;t.after(()=>{if(old===undefined)delete process.env.NEXORA_API_URL;else process.env.NEXORA_API_URL=old})
  process.env.NEXORA_API_URL='http://127.0.0.1:8123';const calls=[]
  t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({path:url.pathname,body:options.body,method:options.method});return Response.json(url.pathname.endsWith('/login')?{token:'test',user:{id:1}}:[])})
  await callBackend('login',{})
  await callBackend('changeJournalStatus',{id:2,version:3,action:'post',reason:'核对',status:'posted'})
  assert.deepEqual(calls.at(-1),{path:'/api/v1/finance/journals/2/post',method:'POST',body:JSON.stringify({version:3,reason:'核对'})})
  await callBackend('reverseJournal',{id:2,version:4,reference:'REV',journal_date:'2026-01-20',reason:'更正',lines:[]})
  assert.deepEqual(JSON.parse(calls.at(-1).body),{version:4,reference:'REV',journal_date:'2026-01-20',reason:'更正'})
  await assert.rejects(callBackend('changeJournalStatus',{id:2,action:'../users'}),/不允许的凭证状态操作/)
  for(const action of ['changeJournalStatus','updateJournal','reverseJournal','journalChanges'])await assert.rejects(callBackend(action,{id:'../users'}),/记录编号无效/)
})

// 排队写入必须在实际发送时重新核对实例，不只比较请求后的返回。
test('凭证写入拒绝旧审批动作、缺批准过账和换服务端后的排队请求', async t=>{
  const old=globalThis.window;t.after(()=>{globalThis.window=old})
  const state=createAppState();state.server.value={id:'A',fingerprint:'a'};state.user.value={id:1,roles:['admin'],permissions:['journal.post']}
  const calls=[];globalThis.window={nexora:{callApi:async(...args)=>{calls.push(args)}}}
  let queued;const actions=createJournalActions(state,async fn=>{queued=fn})
  const row={id:1,version:3,status:'approved',approval:{status:'approved'}}
  assert.equal(await actions.changeJournalStatus({...row,approval:undefined},'post','核对'),false)
  assert.equal(await actions.changeJournalStatus(row,'approve','核对'),false);assert.equal(calls.length,0)
  await actions.changeJournalStatus(row,'post','核对');state.server.value={id:'B',fingerprint:'b'}
  await assert.rejects(queued(),/会话或连接已变化/);assert.equal(calls.length,0)
})
