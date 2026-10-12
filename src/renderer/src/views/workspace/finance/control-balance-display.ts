import type { ControlBalanceEvidence, ControlBalanceTransfer, ControlScopeChoice, ControlScopeGroup, ControlScopeIdentity } from '../../../../../shared/control-balance-api'
import { cents } from './subledger-order-display.ts'

export const controlOperationLabels = { reclassify: '原单余额重分类', allocate: '跨原单贷方分配' } as const
export const controlKindLabels = { receivable: '客户应收', payable: '供应商应付' } as const
export const controlCombinationKey = (scope: Pick<ControlScopeIdentity, 'account_id' | 'auxiliary'>) => `${scope.account_id}:` + scope.auxiliary.map(item => `${item.kind}:${item.id}`).sort().join('|')
export const controlGroupKey = (scope: ControlScopeIdentity) => `${scope.kind}:${scope.source_type}:${scope.source_id}:` + controlCombinationKey(scope)
export const controlChoice = (group: ControlScopeGroup): ControlScopeChoice => ({ source_type: group.source_type, source_id: group.source_id,
  account_id: group.account_id, auxiliary: group.auxiliary.map(({ kind, id }) => ({ kind, id })), fingerprint: group.fingerprint })
export function controlTransferLimit(source: ControlScopeGroup | undefined, target: ControlScopeGroup | undefined,
  operation: 'reclassify' | 'allocate'): bigint {
  if (!source || source.blockers.length) return 0n
  const balance = cents(source.outstanding_amount)
  if (operation === 'reclassify') return balance < 0n ? -balance : balance
  if (!target || target.blockers.length || target.kind !== source.kind || target.party_id !== source.party_id
    || target.source_id === source.source_id && target.source_type === source.source_type || controlCombinationKey(source) === controlCombinationKey(target)) return 0n
  const debt = cents(target.outstanding_amount), credit = -balance
  return debt > 0n && credit > 0n ? debt < credit ? debt : credit : 0n
}
export function controlCaption(row: ControlBalanceTransfer): string {
  if (row.status === 'cancelled') return '已取消'
  if (row.status === 'executed') return row.reverses_id ? '反向凭证已过账' : '已过账生效'
  if (row.journal_id && row.journal_status !== 'cancelled') return row.approval?.status === 'approved'
    ? '转账已批准 · 凭证待过账' : '转账缺少当前批准 · 凭证不可过账'
  return { draft: '未送审', submitted: '转账审批中', approved: '转账已批准待生成', rejected: '已驳回', withdrawn: '已撤回', executed: '已生效' }[row.approval?.status ?? 'draft']
}
export function controlEvidenceText(item: ControlBalanceEvidence): string {
  if (item.type === 'journal') return `凭证 #${item.journal_id} · ${item.source_key} · ${item.journal_date} · 分配 ${item.amount} 元`
  if (item.type === 'opening') return `历史分户方案 #${item.opening_id} v${item.opening_version} · ${item.document_reference} · ${item.date} · 借 ${item.debit} / 贷 ${item.credit}`
  if (item.type === 'control_transfer') return `余额转账 #${item.transfer_id} · 凭证 #${item.journal_id} · ${item.date} · 原记录变动 ${item.from_delta} 元`
  if (item.type === 'historical_payment') return `历史资金 #${item.payment_id} · ${item.date} · ${item.amount} 元${item.journal_id ? ' · 凭证 #' + item.journal_id : ' · 凭证待过账'}`
  if (item.type === 'pending_payment') return `订单资金 #${item.payment_id} · ${item.amount} 元 · 已执行待过账`
  if (item.type === 'order_settlement') return `订单核销 #${item.transfer_id} · ${item.executed_at} · ${item.amount} 元`
  return `历史核销 #${item.settlement_id} · ${item.date} · ${item.amount} 元`
}
