import type { SubledgerInput, SubledgerOpening, OpeningBalanceAction } from '../../../../../shared/erp-api'
import { dateFieldError } from '../../../utils/date-field.ts'

export const subledgerKindLabels = { receivable: '客户应收', payable: '供应商应付' }
export function subledgerDraftError(input: SubledgerInput, effectiveDate: string): string {
  if (!input.control_accounts.length || input.control_accounts.some(item => item.account_id <= 0)) return '请选择至少一个往来控制科目。'
  if (new Set(input.control_accounts.map(item => item.account_id)).size !== input.control_accounts.length) return '应收与应付不能使用同一个科目。'
  const keys = new Set<string>()
  for (const [index, line] of input.lines.entries()) {
    const prefix = `第 ${index + 1} 行：`
    if (line.party_id <= 0 || !input.control_accounts.some(item => item.kind === line.kind && item.account_id === line.account_id)) return prefix + '请选择往来对象及对应控制科目。'
    if (!line.document_reference.trim()) return prefix + '请填写原始单据编号。'
    if (dateFieldError(line.document_date, { required: true }) || line.document_date >= effectiveDate) return prefix + '原单日期须有效且早于总账启用日。'
    if (![line.debit,line.credit].every(value => /^\d{1,12}(?:\.\d{1,2})?$/.test(value))
      || (Number(line.debit) > 0) === (Number(line.credit) > 0)) return prefix + '只填写一方正金额，另一方填 0。'
    const key = JSON.stringify([line.kind,line.party_id,line.document_reference.trim()])
    if (keys.has(key)) return prefix + '同一往来对象的原单编号不能重复。'
    keys.add(key)
  }
  return ''
}
export function subledgerActions(item: SubledgerOpening, permissions: string[], userId: number): OpeningBalanceAction[] {
  const can = (action: string) => permissions.includes('subledger_opening.' + action)
  const result: OpeningBalanceAction[] = []
  // 审核动作由统一弹窗按服务端步骤资格显示，执行动作还需本单批准。
  if (item.status === 'approved' && item.approval?.status === 'approved' && can('confirm')) result.push('confirm')
  if (['draft','rejected','submitted','approved'].includes(item.status) && can('cancel')
      && !['submitted','approved'].includes(item.approval?.status ?? '')) result.push('cancel')
  if (item.status === 'confirmed' && item.reversal_approval?.status === 'approved' && can('reverse')) result.push('reverse')
  return result
}
