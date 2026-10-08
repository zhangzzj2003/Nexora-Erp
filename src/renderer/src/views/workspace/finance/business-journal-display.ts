import type { BusinessJournalEvidence, BusinessJournalRole, BusinessJournalMapping } from '../../../../../shared/erp-api'
import { journalTotals } from './journal-display.ts'

export const businessRoleLabels: Record<BusinessJournalRole, string> = {
  inventory: '库存', payable: '应付', receivable: '应收', income: '销售收入', sales_cost: '销售成本',
  cash: '收付款资金', price_variance: '采购价差', work_in_progress: '生产在制成本',
  labor_accrual: '人工费用对方', overhead_accrual: '制造费用对方', inventory_offset: '其他库存变动对方'
}
export function businessSourceMapping(source: BusinessJournalEvidence, configured?: BusinessJournalMapping): BusinessJournalMapping {
  const mapping = {...configured}
  const record = source.source_type === 'subledger_payment' ? source.records[0] : undefined
  if (record && (record.kind === 'receivable' || record.kind === 'payable')
    && typeof record.account_id === 'number' && Number.isSafeInteger(record.account_id) && record.account_id > 0) {
    mapping[record.kind] = record.account_id
  }
  return mapping
}
export function businessRoleRows(source: BusinessJournalEvidence) {
  return Object.entries(source.roles).map(([role, amount]) => ({
    role: role as BusinessJournalRole, label: businessRoleLabels[role as BusinessJournalRole],
    debit: amount!.startsWith('-') ? '0.00' : amount!, credit: amount!.startsWith('-') ? amount!.slice(1) : '0.00'
  }))
}
export function businessTotal(source: BusinessJournalEvidence): string {
  return journalTotals(businessRoleRows(source).map(row => ({ ...row, account_id: 1, summary: row.label }))).debit
}
