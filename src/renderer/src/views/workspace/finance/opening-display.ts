import type { OpeningBalanceAction, OpeningBalanceStatus, JournalLineInput } from '../../../../../shared/erp-api'
import { journalTotals } from './journal-display.ts'

export const openingStatusLabels: Record<OpeningBalanceStatus, string> = {
  draft: '草稿', submitted: '待审核', approved: '已批准', rejected: '已驳回', confirmed: '已确认', cancelled: '已取消', reversed: '已撤销'
}
export const openingActionLabels: Record<OpeningBalanceAction | 'create' | 'update' | 'withdraw', string> = {
  withdraw: '撤回审批', create: '建立', update: '修改', submit: '提交', approve: '批准', reject: '驳回', confirm: '确认期初', cancel: '取消草稿', reverse: '撤销期初'
}
export function openingTotals(lines: JournalLineInput[]) {
  if (lines.length === 0) return { debit: '0.00', credit: '0.00', balanced: true }
  const result = journalTotals(lines)
  const keys = lines.map(line => JSON.stringify([line.account_id,
    (line.auxiliary ?? []).map(item => [item.kind, item.id]).sort((a, b) => String(a[0]).localeCompare(String(b[0])))]))
  return { ...result, balanced: result.balanced && new Set(keys).size === lines.length }
}
