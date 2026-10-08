import type { OtherInbound } from '../../../../../shared/erp-api'

export type OtherInboundFilter = 'all' | 'pending' | 'processed' | 'cancelled' | 'reversed'
type InboundState = Pick<OtherInbound, 'status' | 'reversal_id'>

// 仓库终态优先于审批进度；批准但尚未入库的单据仍需要继续处理。
export function otherInboundGroup(inbound: InboundState): Exclude<OtherInboundFilter, 'all'> {
  if (inbound.status === 'cancelled') return 'cancelled'
  if (inbound.status === 'posted') return inbound.reversal_id ? 'reversed' : 'processed'
  return 'pending'
}

// 统计使用完整可见快照，互斥分组保证各状态数量之和等于全部单据。
export function otherInboundSummary(inbounds: readonly InboundState[]): Record<OtherInboundFilter, number> {
  const summary = { all: inbounds.length, pending: 0, processed: 0, cancelled: 0, reversed: 0 }
  for (const inbound of inbounds) summary[otherInboundGroup(inbound)] += 1
  return summary
}
