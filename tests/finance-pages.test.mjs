import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref, toRaw } from 'vue'
import { createMemoryHistory } from 'vue-router'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import { visibleRouteGroups, workspaceRoutes, permittedOpenedRoutes } from '../src/renderer/src/router/workspace-routes.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createFinanceActions } from '../src/renderer/src/store/modules/finance-actions.ts'
import { submitCreateDialog } from '../src/renderer/src/utils/create-dialog.ts'

test('三个财务页面分别注册，保留原地址并统一拦截未授权访问', async () => {
  const keys = ['finance', 'financePayments', 'financeSources']
  const group = visibleRouteGroups(['finance.view']).find(group => group.key === 'finance')
  assert.deepEqual(group.routes.map(route => route.key), keys)
  assert.deepEqual(group.routes.map(route => route.label), ['应收应付', '收付款记录', '应收应付来源'])
  assert.equal(group.routes[0].path, '/workspace/finance')
  const component = { render: () => null }
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, component])))
  let permissions = ['finance.view']
  installWorkspaceAccessGuard(router, () => permissions)
  for (const route of group.routes) {
    await router.push(route.path)
    assert.equal(router.currentRoute.value.name, route.key)
  }
  // 权限撤销后既清理已打开标签，也拦截直接地址；操作权限不能代替查看权限。
  assert.deepEqual(permittedOpenedRoutes(keys, []), [])
  permissions = ['finance.record', 'finance.reverse']
  await router.push('/workspace/home')
  for (const route of group.routes) {
    await router.push(route.path)
    assert.equal(router.currentRoute.value.name, 'home')
  }
})

test('登记页继续保留失败草稿，退款成功仅清空凭据字段，冲销失败保留原因', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const paymentForm = ref({ kind: 'receivable', order_id: 12, action: 'refund', amount: '10', reference: 'REF-12', note: '退货退款' })
  const reversalReasons = ref({ 9: '重复登记' })
  const draft = structuredClone(toRaw(paymentForm.value))
  const state = { busy: ref(false), error: ref(''), notice: ref('') }
  const calls = []
  let fail = true
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls.push([action, structuredClone(payload)])
    if (fail) throw new Error('服务端拒绝本次操作')
  } } }
  const actions = createFinanceActions({ ...createAppState(), user: ref({id:1,permissions:['finance.record','finance.reverse']}), paymentForm, reversalReasons }, async (action, success) => {
    state.error.value = ''
    try { await action(); state.notice.value = success }
    catch (error) { state.error.value = error.message }
  })
  const open = ref(true)
  await submitCreateDialog(actions.createPaymentRecord, state, open)
  assert.equal(open.value, true)
  assert.deepEqual(paymentForm.value, draft)
  await actions.reversePaymentRecord(9)
  assert.equal(reversalReasons.value[9], '重复登记')
  fail = false
  await submitCreateDialog(actions.createPaymentRecord, state, open)
  assert.equal(open.value, false)
  assert.deepEqual(paymentForm.value, { ...draft, amount: '', reference: '', note: '' })
  await actions.reversePaymentRecord(9)
  assert.equal(reversalReasons.value[9], undefined)
  assert.deepEqual(calls, [
    ['createPaymentRecord', draft],
    ['reversePaymentRecord', { paymentId: 9, reason: '重复登记' }],
    ['createPaymentRecord', draft],
    ['reversePaymentRecord', { paymentId: 9, reason: '重复登记' }]
  ])
})

test('订单间核销失败保留依据，成功清空金额及凭据，撤销失败保留原因', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  const orderSettlementForm = ref({ kind: 'receivable', from_order_id: 7, to_order_id: 8,
    amount: '6.00', reference: 'OFFSET-7', reason: '同一客户贷方抵扣' })
  const orderSettlementReversalReasons = ref({ 3: '原单关联错误' })
  const calls = []
  let fail = true
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls.push([action, structuredClone(payload)])
    if (fail) throw new Error('核销余额已变化')
  } } }
  const state = { busy: ref(false), error: ref(''), notice: ref('') }
  const actions = createFinanceActions({ ...createAppState(), orderSettlementForm, orderSettlementReversalReasons },
    async (action, success) => {
      state.error.value = ''
      try { await action(); state.notice.value = success }
      catch (error) { state.error.value = error.message }
    })
  const open = ref(true)
  await submitCreateDialog(actions.createOrderSettlement, state, open)
  assert.equal(open.value, true)
  assert.equal(orderSettlementForm.value.reference, 'OFFSET-7')
  await actions.reverseOrderSettlement(3)
  assert.equal(orderSettlementReversalReasons.value[3], '原单关联错误')
  fail = false
  await submitCreateDialog(actions.createOrderSettlement, state, open)
  assert.equal(open.value, false)
  assert.deepEqual(orderSettlementForm.value, { kind: 'receivable', from_order_id: 7,
    to_order_id: 8, amount: '', reference: '', reason: '' })
  await actions.reverseOrderSettlement(3)
  assert.equal(orderSettlementReversalReasons.value[3], undefined)
  assert.deepEqual(calls, [
    ['createOrderSettlement', { kind: 'receivable', from_order_id: 7, to_order_id: 8,
      amount: '6.00', reference: 'OFFSET-7', reason: '同一客户贷方抵扣' }],
    ['reverseOrderSettlement', { transferId: 3, reason: '原单关联错误' }],
    ['createOrderSettlement', { kind: 'receivable', from_order_id: 7, to_order_id: 8,
      amount: '6.00', reference: 'OFFSET-7', reason: '同一客户贷方抵扣' }],
    ['reverseOrderSettlement', { transferId: 3, reason: '原单关联错误' }]
  ])
})

// 批准本身不执行资金；排队时换服务端使原确认失效，不触发新的网络写入。
test('资金确认保护批准状态与排队会话，失败不清除新账号草稿',async t=>{
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  const state=createAppState();state.user.value={id:1,roles:['finance'],permissions:['finance.record']}
  state.server.value={id:'source',fingerprint:'source-ca'}
  let resume;const pending=new Promise(resolve=>{resume=resolve}),calls=[]
  globalThis.window={nexora:{callApi:async(...args)=>{calls.push(args)}}}
  const actions=createFinanceActions(state,async fn=>{await pending;try{await fn()}catch(e){state.error.value=e.message}})
  const row={id:1,version:1,status:'draft',reverses_id:null}
  await actions.changePaymentRecordStatus(row,'post','提前执行');assert.equal(calls.length,0)
  const run=actions.changePaymentRecordStatus({...row,approval:{status:'approved'}},'post','核对执行')
  state.server.value={id:'destination',fingerprint:'destination-ca'};resume();await run
  assert.equal(calls.length,0);assert.match(state.error.value,/会话或连接已变化/)
})
