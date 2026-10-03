import type {
  FinancialEntry,
  Movement,
  PaymentRecord
} from '../../../shared/erp-api'

// 格式化只依赖输入数据，页面和测试可直接复用。
export const movementTypeLabels: Record<string, string> = {
  receipt: '采购入库', receipt_reversal: '采购入库冲销',
  other_inbound: '其他入库', other_inbound_reversal: '其他入库冲销',
  other_outbound: '其他出库', other_outbound_reversal: '其他出库冲销',
  shipment: '销售出库', shipment_reversal: '销售出库冲销',
  purchase_return: '采购退货', purchase_return_reversal: '采购退货冲销',
  sales_return: '销售退货', sales_return_reversal: '销售退货冲销',
  transfer_in: '调拨入库', transfer_out: '调拨出库',
  transfer_reversal_in: '调拨入库冲销', transfer_reversal_out: '调拨出库冲销',
  adjustment: '库存调整', adjustment_reversal: '库存调整冲销',
  stocktake: '盘点', stocktake_reversal: '盘点冲销',
  material_issue: '生产领料', material_issue_reversal: '生产领料冲销',
  material_return: '生产退料',
  material_return_reversal: '生产退料冲销',
  production_completion: '生产完工', production_completion_reversal: '生产完工冲销'
}

export function movementTypeLabel(sourceType: string): string {
  return movementTypeLabels[sourceType] ?? '未识别的库存来源'
}

export function displayError(cause: unknown): string {
  const message = cause instanceof Error ? cause.message : '操作失败'
  return message.replace(/^Error invoking remote method '[^']+': Error: /, '')
}

export function localTime(value: string): string {
  // SQLite 的 CURRENT_TIMESTAMP 是 UTC，展示时换算成用户设备的本地时区。
  const normalized = value.replace(' ', 'T')
  const date = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : normalized + 'Z')
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false })
}

export function movementSource(item: Movement): string {
  // 所有库存变动都显示原始业务单据，便于从数量追溯到责任操作。
  if (item.receipt_id !== null) return `入库单 #${item.receipt_id}`
  if (item.receipt_reversal_id !== null)
    return `入库冲销单 #${item.receipt_reversal_id}`
  if (item.other_inbound_id !== null) return `其他入库单 #${item.other_inbound_id}`
  if (item.other_inbound_reversal_id !== null)
    return `其他入库冲销单 #${item.other_inbound_reversal_id}`
  if (item.other_outbound_id !== null) return `其他出库单 #${item.other_outbound_id}`
  if (item.other_outbound_reversal_id !== null)
    return `其他出库冲销单 #${item.other_outbound_reversal_id}`
  if (item.adjustment_id !== null) return `库存调整单 #${item.adjustment_id}`
  if (item.adjustment_reversal_id !== null)
    return `库存调整冲销单 #${item.adjustment_reversal_id}`
  if (item.transfer_id !== null) return `调拨单 #${item.transfer_id}`
  if (item.transfer_reversal_id !== null)
    return `调拨冲销单 #${item.transfer_reversal_id}`
  if (item.stocktake_id !== null) return `盘点单 #${item.stocktake_id}`
  if (item.stocktake_reversal_id !== null)
    return `盘点冲销单 #${item.stocktake_reversal_id}`
  if (item.shipment_id !== null) return `出库单 #${item.shipment_id}`
  if (item.shipment_reversal_id !== null)
    return `出库冲销单 #${item.shipment_reversal_id}`
  if (item.sales_return_id !== null)
    return `销售退货单 #${item.sales_return_id}`
  if (item.sales_return_reversal_id !== null)
    return `销售退货冲销单 #${item.sales_return_reversal_id}`
  if (item.purchase_return_id !== null)
    return `采购退货单 #${item.purchase_return_id}`
  if (item.purchase_return_reversal_id !== null)
    return `采购退货冲销单 #${item.purchase_return_reversal_id}`
  if (item.material_issue_id !== null)
    return `生产领料单 #${item.material_issue_id}`
  if (item.material_issue_reversal_id !== null)
    return `生产领料冲销单 #${item.material_issue_reversal_id}`
  if (item.material_return_id !== null)
    return `生产退料单 #${item.material_return_id}`
  if (item.material_return_reversal_id !== null)
    return `生产退料冲销 #${item.material_return_reversal_id}`
  if (item.production_completion_id !== null)
    return `生产完工单 #${item.production_completion_id}`
  if (item.production_completion_reversal_id !== null)
    return `生产完工冲销单 #${item.production_completion_reversal_id}`
  return `流水 #${item.id}`
}

export function financialSource(item: FinancialEntry): string {
  const names = {
    shipment: '销售出库',
    shipment_reversal: '销售出库冲销',
    sales_return: '销售退货',
    sales_return_reversal: '销售退货冲销',
    receipt: '采购入库',
    receipt_reversal: '采购入库冲销',
    purchase_return: '采购退货',
    purchase_return_reversal: '采购退货冲销',
    after_sales_repair: '售后维修服务费', after_sales_repair_reversal: '售后维修服务费更正'
  }
  return `${names[item.source_type]} #${item.source_id}`
}

export function paymentActionLabel(item: PaymentRecord): string {
  if (item.action === 'reversal') return '冲销'
  if (item.kind === 'receivable')
    return item.action === 'settlement' ? '客户收款' : '客户退款'
  return item.action === 'settlement' ? '供应商付款' : '供应商退款'
}
