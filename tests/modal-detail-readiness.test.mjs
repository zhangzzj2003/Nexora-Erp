import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createStatementActions } from '../src/renderer/src/store/modules/statement-actions.ts'
import { createLedgerReportActions } from '../src/renderer/src/store/modules/ledger-report-actions.ts'
import { createControlBalanceActions } from '../src/renderer/src/store/modules/control-balance-actions.ts'
import { createPeriodClosingActions } from '../src/renderer/src/store/modules/period-closing-actions.ts'
import { createSubledgerActions } from '../src/renderer/src/store/modules/subledger-actions.ts'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const permissions = ['financial_statement.view', 'journal.view', 'control_transfer.view',
  'accounting_period.closing_view', 'subledger_opening.view']
// 各业务使用自己的 store，只共享行为断言，防止统一动画把任一领域的失效边界漏掉。
const domains = [
  { name: '报表归档', create: state => createStatementActions(state, run => run()),
    load: (actions, id) => actions.openStatementArchive(id), close: actions => actions.closeStatementArchive(),
    displayed: state => state.statementArchive.value, response: (_, { id }) => ({ id, snapshot: { csv: `archive-${id}` } }) },
  { name: '报表凭证', create: createLedgerReportActions,
    load: (actions, id) => actions.openLedgerReportJournal(id), close: actions => actions.closeLedgerReportJournal(),
    displayed: state => state.ledgerReportJournal.value, response: (_, { id }) => ({ id, version: 1 }) },
  { name: '转账原始依据', create: state => createControlBalanceActions(state, run => run(), async () => {}),
    load: (actions, id) => actions.loadControlBalanceDetail(id), close: actions => actions.closeControlBalanceDetail(),
    displayed: state => state.controlBalanceDetail.value,
    response: (operation, { id }) => operation === 'controlBalanceChanges' ? [{ id }] : { id, evidence: {} } },
  { name: '转账关联凭证', create: state => createControlBalanceActions(state, run => run(), async () => {}),
    load: (actions, id) => actions.loadControlBalanceJournal(id), close: actions => actions.closeControlBalanceJournal(),
    displayed: state => state.controlBalanceJournal.value, response: (_, { id }) => ({ id, version: 1 }) },
  { name: '期间检查', create: state => createPeriodClosingActions(state, run => run()),
    load: (actions, id) => actions.loadPeriodClosingCheck(id), close: actions => actions.closePeriodClosing(),
    displayed: state => state.periodClosingCheck.value, response: (_, { id }) => ({ period: { id }, can_close: true }) },
  { name: '分户核对', create: state => createSubledgerActions(state, run => run()),
    load: (actions, id) => actions.loadSubledgerDetail({ id, status: 'draft' }), close: actions => actions.clearSubledgerDetail(),
    displayed: state => state.subledgerCheck.value,
    response: (operation, { id }) => operation === 'subledgerChanges' ? [{ id }] : { id, matched: true } }
]
for (const domain of domains) {
  test(`${domain.name}同目标刷新不闪空，失败不报就绪，关闭和会话变更拒绝迟到展开`, async t => {
    const old = globalThis.window, scope = effectScope(), state = createAppState()
    t.after(() => { scope.stop(); globalThis.window = old })
    state.user.value = { id: 1, roles: ['viewer', 'finance'], permissions: [...permissions] }
    state.server.value = { id: 'first', fingerprint: 'cert-a' }
    let waiting = false
    const tasks = []
    globalThis.window = { nexora: { callApi: (operation, input) => {
      const result = domain.response(operation, input)
      if (!waiting) return Promise.resolve(result)
      const task = deferred(); tasks.push({ ...task, result }); return task.promise
    } } }
    const actions = scope.run(() => domain.create(state))
    assert.equal(await domain.load(actions, 1), true)
    const displayed = domain.displayed(state)
    waiting = true
    const refresh = domain.load(actions, 1)
    assert.equal(domain.displayed(state), displayed)
    // 相同账号的 me 快照即使重排角色与权限，也不能取消正在等待的同一单据。
    state.user.value = { ...state.user.value, roles: [...state.user.value.roles].reverse(), permissions: [...permissions].reverse() }
    assert.equal(domain.displayed(state), displayed)
    tasks.splice(0).forEach(task => task.reject(Error('详情暂不可用')))
    assert.equal(await refresh, false)
    assert.equal(domain.displayed(state), displayed)
    const next = domain.load(actions, 2)
    assert.equal(domain.displayed(state), null)
    domain.close(actions)
    tasks.splice(0).forEach(task => task.resolve(task.result))
    assert.equal(await next, false)
    assert.equal(domain.displayed(state), null)
    const switched = domain.load(actions, 1)
    state.server.value = { id: 'first', fingerprint: 'cert-b' }
    tasks.splice(0).forEach(task => task.resolve(task.result))
    assert.equal(await switched, false)
    assert.equal(domain.displayed(state), null)
    const disconnected = domain.load(actions, 1)
    state.connectionLost.value = true
    tasks.splice(0).forEach(task => task.resolve(task.result))
    assert.equal(await disconnected, false)
    assert.equal(domain.displayed(state), null)
  })
}
