import type { AuxiliarySnapshot, OrderScopeGroup, SubledgerOrderDirection, SubledgerOrderLine, SubledgerOrderOption } from '../../../../../shared/erp-api'

export const directionLabels = { historical_credit: '历史贷方抵订单', order_credit: '订单贷方抵历史' } as const
export function cents(value: string): bigint {
  if (!/^-?\d+(\.\d{1,2})?$/.test(value)) return 0n
  const negative = value.startsWith('-'); const [whole, fraction = ''] = value.replace('-', '').split('.')
  return (BigInt(whole!) * 100n + BigInt(fraction.padEnd(2, '0'))) * (negative ? -1n : 1n)
}
export function amountText(value: bigint): string {
  const negative = value < 0n; const absolute = negative ? -value : value
  return `${negative ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
}
const auxiliaryKey = (values: AuxiliarySnapshot[]) => values.map(item => `${item.kind}:${item.id}`).sort().join('|')
export function matchingGroup(line: SubledgerOrderLine, order: SubledgerOrderOption): OrderScopeGroup | undefined {
  if (line.kind !== order.kind || line.party_id !== order.party_id || order.blockers.length) return undefined
  return order.groups.find(group => group.account_id === line.account_id && group.evidence.length > 0
    && auxiliaryKey(group.auxiliary) === auxiliaryKey(line.auxiliary))
}
export function matchingLimit(line: SubledgerOrderLine, order: SubledgerOrderOption, direction: SubledgerOrderDirection): bigint {
  const group = matchingGroup(line, order)
  if (!group) return 0n
  const history = cents(line.outstanding_amount), live = cents(order.outstanding_amount), scoped = cents(group.outstanding_amount)
  const limits = direction === 'historical_credit' ? [-history, live, scoped] : [history, -live, -scoped]
  const limit = limits.reduce((minimum, value) => value < minimum ? value : minimum)
  return limit > 0n ? limit : 0n
}
