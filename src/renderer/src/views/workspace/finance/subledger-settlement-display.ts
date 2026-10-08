import type { SubledgerBalanceRow, SubledgerSettlement } from '../../../../../shared/erp-api'

export function sameSubledgerScope(source: SubledgerBalanceRow, target: SubledgerBalanceRow): boolean {
  const auxiliaryKey = (row: SubledgerBalanceRow) => row.auxiliary.map(item => `${item.kind}:${item.id}`).sort().join('|')
  return source.id !== target.id && source.opening_id === target.opening_id && source.kind === target.kind
    && source.party_id === target.party_id && source.account_id === target.account_id && auxiliaryKey(source) === auxiliaryKey(target)
}

export function settlementActions(item: Pick<SubledgerSettlement, 'status' | 'reverses_id' | 'approval'>, permissions: string[]): ('post' | 'cancel')[] {
  if (item.status !== 'draft' || !permissions.includes(item.reverses_id ? 'finance.reverse' : 'finance.record')) return []
  return item.approval?.status === 'approved' ? ['post'] : item.approval?.status === 'submitted' ? [] : ['cancel']
}

export function canReverseSettlement(item: Pick<SubledgerSettlement, 'id' | 'status' | 'reverses_id'>,
  records: Pick<SubledgerSettlement, 'reverses_id' | 'status'>[]): boolean {
  return item.status === 'executed' && item.reverses_id === null
    && !records.some(row => row.reverses_id === item.id && row.status !== 'cancelled')
}
