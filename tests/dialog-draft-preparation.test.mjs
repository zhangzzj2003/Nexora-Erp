import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createJournalActions } from '../src/renderer/src/store/modules/journal-actions.ts'
import { createOpeningBalanceActions } from '../src/renderer/src/store/modules/opening-balance-actions.ts'
import { createSubledgerActions } from '../src/renderer/src/store/modules/subledger-actions.ts'

const cases = [
  { name: '凭证', create: createJournalActions, open: 'editJournal', cancel: 'cancelJournalPreparation',
    form: 'journalForm', options: 'journalOptions', rejects: true,
    result: { accounts: [], periods: [] } },
  { name: '总账期初', create: createOpeningBalanceActions, open: 'editOpeningBalance', cancel: 'cancelOpeningBalancePreparation',
    form: 'openingBalanceForm', options: 'openingBalanceOptions', result: { accounts: [], period: null } },
  { name: '分户期初', create: createSubledgerActions, open: 'editSubledger', cancel: 'cancelSubledgerPreparation',
    form: 'subledgerForm', options: 'subledgerOptions', result: { opening_balance: null } }
]
const permissions = ['journal.create', 'opening_balance.create', 'subledger_opening.create']
const row = id => ({ id, version: 1, reference: `目标-${id}`, journal_date: '2026-01-01',
  effective_date: '2026-01-01', opening_balance_id: 1, opening_version: 1, note: '', lines: [], control_accounts: [] })

// 三种公共编辑准备保留原有返回契约，统一核对真正写入 Pinia 的数据边界。
for (const entry of cases) test(`${entry.name}取消等待保留草稿，迟到请求不能覆盖重开结果或新会话输入`, async t => {
  const previous = globalThis.window, scope = effectScope(), state = createAppState(), reads = []
  t.after(() => { scope.stop(); globalThis.window = previous })
  state.user.value = { id: 1, roles: ['finance', 'viewer'], permissions: [...permissions] }
  state.server.value = { id: 'instance', fingerprint: 'first' }
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => reads.push(resolve)) } }
  const actions = scope.run(() => entry.create(state, action => action()))
  const open = id => actions[entry.open](row(id)).then(value => ({ value }), error => ({ error }))
  const assertCancelled = outcome => {
    if (entry.rejects) assert.match(outcome.error?.message ?? '', /会话或权限已变化/)
    else assert.equal(outcome.value, false)
  }
  state[entry.form].value.reference = '已填写的草稿'
  const oldDraft = state[entry.form].value, oldOptions = state[entry.options].value
  const cancelled = open(1)
  actions[entry.cancel]()
  assert.equal(state[entry.form].value, oldDraft)
  reads.shift()(entry.result)
  assertCancelled(await cancelled)
  assert.equal(state[entry.form].value, oldDraft)
  assert.equal(state[entry.options].value, oldOptions)

  const oldOpen = open(1)
  actions[entry.cancel]()
  const reopened = open(2)
  const finishOld = reads.shift(), finishNew = reads.shift()
  finishNew(entry.result)
  assert.equal((await reopened).error, undefined)
  assert.equal(state[entry.form].value.reference, '目标-2')
  finishOld(entry.result)
  assertCancelled(await oldOpen)
  assert.equal(state[entry.form].value.reference, '目标-2')

  const disconnected = open(3)
  state.connectionLost.value = true
  state.connectionLost.value = false
  reads.shift()(entry.result)
  assertCancelled(await disconnected)
  assert.equal(state[entry.form].value.reference, '目标-2')

  const stable = open(4)
  state.user.value = { ...state.user.value, roles: [...state.user.value.roles].reverse(), permissions: [...permissions].reverse() }
  reads.shift()(entry.result)
  assert.equal((await stable).error, undefined)
  assert.equal(state[entry.form].value.reference, '目标-4')

  const differentServer = open(5)
  state.server.value = { ...state.server.value, fingerprint: 'second' }
  state[entry.form].value.reference = '新实例草稿'
  reads.shift()(entry.result)
  assertCancelled(await differentServer)
  assert.equal(state[entry.form].value.reference, '新实例草稿')
})
