// 采购入库确认时固定实物批次；供应商批号缺失时仍保留独立的内部来源编号。
export interface ReceiptLotPartInput {
  quantity: string
  supplier_lot: string | null
  manufactured_on: string | null
  expires_on: string | null
}

export type PhysicalLotPartInput = ReceiptLotPartInput

export interface InboundLotLineInput {
  inbound_line_id: number
  // 分批确认携带读取时的实收量，服务端据此拒绝重复提交与过期草稿。
  expected_received_quantity?: string
  lots: PhysicalLotPartInput[]
}

export interface ReceiptLotLineInput {
  receipt_line_id: number
  lots: ReceiptLotPartInput[]
}

export interface ReceiptPhysicalLot {
  id: number
  code: string
  quantity: string
  supplier_lot: string | null
  manufactured_on: string | null
  expires_on: string | null
}

export function receiptLotMilli(value: string): bigint | null {
  if (!/^\d{1,7}(?:\.\d{1,3})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  const milli = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
  return milli > 0n && milli <= 1_000_000_000n ? milli : null
}

// 检查点允许零，实际批次仍须大于零；统一使用整数千分位避免舍入。
export function inboundReceivedMilli(value: string): bigint | null {
  if (!/^\d{1,7}(?:\.\d{1,3})?$/.test(value)) return null
  return /^0(?:\.0{1,3})?$/.test(value) ? 0n : receiptLotMilli(value)
}

export function receiptLotDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
