import type { JournalAction, JournalLineInput, JournalStatus } from '../../../../../shared/erp-api'

export const journalStatusLabels: Record<JournalStatus, string> = {
  draft: '草稿', submitted: '待审核', approved: '已批准', rejected: '已驳回', posted: '已过账', cancelled: '已取消'
}
export const journalActionLabels: Record<JournalAction | 'reverse' | 'create' | 'update' | 'withdraw', string> = {
  withdraw: '撤回审批', create: '建立', update: '修改', submit: '提交', approve: '批准', reject: '驳回', post: '过账', cancel: '取消凭证', reverse: '建立冲销'
}

// 页面提示也按整数分相加，避免 0.1 + 0.2 的浮点误差阻止有效凭证。
export function journalTotals(lines: JournalLineInput[]): { debit: string; credit: string; balanced: boolean } {
  let debit = 0n; let credit = 0n; let valid = lines.length >= 2
  for (const line of lines) {
    const values = [line.debit, line.credit].map(value => {
      if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(value)) { valid = false; return 0n }
      const [whole, fraction = ''] = value.split('.')
      return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
    })
    if ((values[0]! > 0n) === (values[1]! > 0n)) valid = false
    debit += values[0]!; credit += values[1]!
  }
  const amount = (value: bigint): string => `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
  return { debit: amount(debit), credit: amount(credit), balanced: valid && debit === credit }
}
