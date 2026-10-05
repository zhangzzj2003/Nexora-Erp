import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createBankBalanceActions } from '../src/renderer/src/store/modules/bank-balance-actions.ts'
import { bankBalanceReportCsv } from '../src/renderer/src/utils/bank-balance-csv.ts'

const snapshot = {
  account_id: 2, account_code: 'BANK-01', ledger_account_id: 3, ledger_code: '1002',
  effective_date: '2026-01-01', as_of_date: '2026-01-31', bank_opening: '100.00',
  bank_movements: '-12.30', bank_closing_computed: '87.70', bank_closing_declared: '87.70',
  book_opening: '100.00', book_movements: '-12.30', book_closing: '87.70',
  bank_unmatched: [{ id: 11, occurred_on: '2026-01-30', transaction_id: '@BANK-11',
    counterparty: '=HYPERLINK("https://example.test")', amount: '-12.30' }],
  book_unmatched: [{ id: 21, journal_id: 5, journal_date: '2026-01-30',
    reference: '记-5', summary: '付款', amount: '-12.30' }],
  bank_opening_unmatched: [{ id: 31, account_id: 2, side: 'bank', occurred_on: '2025-12-30',
    amount: '1.00', reference: '+OLD', description: '原始"凭据"\n两行', created_by: 1, created_at: '2026-01-01' }],
  book_opening_unmatched: [], adjusted_bank: '87.70', adjusted_book: '87.70',
  bank_statement_balanced: true, balanced: true, fingerprint: 'fingerprint-1',
  matched_evidence: [{ group_id: 7, bank_line_ids: [1], journal_line_ids: [2] }],
  clearance_evidence: [{ clearance_id: 8, opening_item_id: 31, source_ids: [4] }]
}
const report = {
  id: 9, account_id: 2, as_of_date: '2026-01-31', declared_bank_closing: '87.70',
  fingerprint: 'fingerprint-1', snapshot_json: '{}', snapshot, reason: '月末核对',
  created_by: 1, created_by_name: 'admin', created_at: '2026-02-01',
  status: 'approved', stale: true,
  decisions: [{ id: 3, report_id: 9, action: 'approve', reason: '复核通过',
    created_by: 2, created_by_name: 'reviewer', created_at: '2026-02-02' }]
}

test('银行调节 CSV 保留原快照金额、来源和状态，并阻止外部字段变为公式', () => {
  const csv = bankBalanceReportCsv(report)
  assert.match(csv, /^\ufeff"类别","项目"/)
  assert.match(csv, /"汇总","调整后银行","","","","87\.70"/)
  assert.match(csv, /"银行未勾对","银行流水","2026-01-30","11","'@BANK-11","-12\.30"/)
  assert.match(csv, /"'=HYPERLINK\(""https:\/\/example\.test""\)"/)
  assert.match(csv, /"'\+OLD","1\.00","原始""凭据""\n两行"/)
  assert.match(csv, /"报表","状态","","已复核","","","来源已变化"/)
  assert.match(csv, /"已勾对来源","分组","","7"/)
  assert.match(csv, /"期初核销来源","核销","","8","31"/)
  assert.match(csv, /"复核记录","复核通过","2026-02-02"/)
  assert.ok(csv.endsWith('\r\n'))
})

test('银行调节 CSV 拒绝报表与快照不一致及伪造金额', () => {
  assert.throws(() => bankBalanceReportCsv({ ...report, fingerprint: 'another' }), /快照.*不一致/)
  assert.throws(() => bankBalanceReportCsv({ ...report,
    snapshot: { ...snapshot, bank_unmatched: [{ ...snapshot.bank_unmatched[0], amount: '=1+1' }] } }), /金额无效/)
})

test('导出只接受当前列表报表，取消和会话切换不写成功提示', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['bank_reconciliation.view'] }
  state.bankBalanceOverview.value = { reports: [report] }
  const saved = []
  let finish
  globalThis.window = { nexora: { saveReportCsv: (...args) => {
    saved.push(args)
    return new Promise(resolve => { finish = resolve })
  } } }
  const actions = createBankBalanceActions(state, async action => { await action() })
  await actions.exportBankBalanceReport(999)
  assert.equal(saved.length, 0)
  const pending = actions.exportBankBalanceReport(9)
  assert.equal(saved[0][0], 'bank-balance-9-2026-01-31.csv')
  assert.match(saved[0][1], /来源已变化/)
  state.user.value = null
  finish('saved.csv')
  await pending
  assert.equal(state.notice.value, '')
  await actions.exportBankBalanceReport(9)
  assert.equal(saved.length, 1)
  state.user.value = { id: 1, permissions: ['bank_reconciliation.view'] }
  state.bankBalanceOverview.value = { reports: [report] }
  const cancelled = actions.exportBankBalanceReport(9)
  finish(null)
  await cancelled
  assert.equal(state.notice.value, '')
  globalThis.window.nexora.saveReportCsv = async () => { throw new Error('磁盘已满') }
  await actions.exportBankBalanceReport(9)
  assert.match(state.error.value, /磁盘已满/)
})
