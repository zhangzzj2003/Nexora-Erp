import type { OtherInbound } from '../../../../../shared/erp-api'
import type { InboundLotLineInput } from '../../../../../shared/receipt-lot-api'
import { inboundReceivedMilli, receiptLotDate, receiptLotMilli } from '../../../../../shared/receipt-lot-api.ts'
import { lotAllocation } from '../../../utils/lot-allocation.ts'

type InboundLine = OtherInbound['lines'][number]

// 旧服务端只支持整单确认，旧草稿仍按零实收显示；部分入库必须使用新服务端返回的检查点。
export function inboundReceived(line: InboundLine, status: OtherInbound['status'] = 'draft'): string {
  return line.received_quantity ?? (status === 'posted' ? line.quantity : '0')
}
export function inboundRemaining(line: InboundLine, status: OtherInbound['status'] = 'draft'): string {
  return line.remaining_quantity ?? (status === 'posted' ? '0' : line.quantity)
}

// 多收提示使用精确差额，仓库按次选择业务用途，不自动追加已批准数量。
export function inboundExcess(inbound: OtherInbound | null, drafts: readonly InboundLotLineInput[]) {
  return (inbound?.lines ?? []).flatMap(line => {
    const draft = drafts.find(item => item.inbound_line_id === line.id)
    if (!draft) return []
    const allocation = lotAllocation(inboundRemaining(line), draft.lots)
    return allocation.status === 'over' ? [{line, quantity: allocation.remaining}] : []
  })
}

export function otherInboundLotIssue(inbound: OtherInbound | null, drafts: readonly InboundLotLineInput[]): string {
  if (!inbound) return '入库单明细已经变化，请重新读取。'
  const pending = inbound.lines.filter(line => inboundReceivedMilli(inboundRemaining(line)) !== 0n)
  if (drafts.length !== pending.length || new Set(drafts.map(line => line.inbound_line_id)).size !== drafts.length)
    return '入库单明细已经变化，请重新读取。'
  let hasReceipt = false
  for (const line of pending) {
    const draft = drafts.find(item => item.inbound_line_id === line.id)
    if (!draft || draft.lots.length > 20) return '入库单明细已经变化，请重新读取。'
    // 页面刷新不能把原草稿自动当成新收货，重复提交先比较累计实收检查点。
    if (draft.expected_received_quantity === undefined || inboundReceivedMilli(draft.expected_received_quantity) === null
        || inboundReceivedMilli(draft.expected_received_quantity) !== inboundReceivedMilli(inboundReceived(line))) return '已入库数量已变化，请重新打开批次登记后操作。'
    const expected = receiptLotMilli(inboundRemaining(line))
    let total = 0n
    for (const part of draft.lots) {
      const value = receiptLotMilli(part.quantity)
      if (value === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      total += value
      if (part.supplier_lot && part.supplier_lot.length > 100) return '来源批号不能超过 100 字。'
      if (part.manufactured_on && !receiptLotDate(part.manufactured_on)) return '生产日期无效。'
      if (part.expires_on && !receiptLotDate(part.expires_on)) return '失效日期无效。'
      if (part.manufactured_on && part.expires_on && part.expires_on < part.manufactured_on)
        return '失效日期不能早于生产日期。'
    }
    if (expected === null) return '剩余待入库数量无效，请刷新后操作。'
    if (total > expected) {
      // 多到货必须有额外业务依据，不能以批次登记绕过原单批准总量。
      const excess = lotAllocation(inboundRemaining(line), draft.lots).remaining
      return `物料 ${line.sku} 超出待入库量 ${inboundRemaining(line)}，溢收 ${excess} ${line.unit}；免费赠品请另建赠品入库单，需要付款请补充采购单据。`
    }
    hasReceipt ||= total > 0n
  }
  return hasReceipt ? '' : '请至少登记一个本次实际到货的批次。'
}
