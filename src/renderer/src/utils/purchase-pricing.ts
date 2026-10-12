// 用整数缩放做十进制四舍五入，避免浮点数让 1.005 元显示成 1.00 元。
export type PurchasePricingMode = 'unit_price' | 'total'
export interface PurchasePriceDraft {
  quantity: string
  pricing_mode: PurchasePricingMode
  unit_price: string
  line_total: string
}
function scaled(value: string, digits: number): bigint | null {
  // number 输入允许 .5 与 1e3；展开指数后再检查精度，与服务端 Decimal 一致。
  if (value.length > 40) return null
  const match = /^\+?(\d+(?:\.\d*)?|\.\d+)(?:[eE]([+-]?\d+))?$/.exec(value)
  if (!match) return null
  const [whole, fraction = ''] = match[1].split('.')
  const exponent = Number(match[2] ?? 0)
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 25) return null
  const shift = digits + exponent - fraction.length
  if (shift < 0) return null
  return BigInt((whole || '0') + fraction) * 10n ** BigInt(shift)
}
function rounded(numerator: bigint, denominator: bigint): bigint {
  return (numerator * 2n + denominator) / (denominator * 2n)
}
function decimal(value: bigint, digits: number): string {
  const padded = value.toString().padStart(digits + 1, '0')
  return `${padded.slice(0, -digits)}.${padded.slice(-digits)}`
}
export function purchasePrice(quantity: string, mode: PurchasePricingMode, source: string): string {
  const count = scaled(quantity, 3)
  if (count === null || count <= 0n || count > 1_000_000_000n) return ''
  const amount = scaled(source, mode === 'total' ? 2 : 4)
  if (amount === null) return ''
  if (mode === 'total') {
    if (amount > 100_000_000n * count) return '' // 反算单价不得超过十亿元。
    return decimal(rounded(amount * 10n ** 13n, count), 12).replace(/\.?0+$/, '') || '0'
  }
  if (amount > 10_000_000_000_000n) return ''
  return decimal(rounded(count * amount, 100_000n), 2)
}
export function recalculatePurchasePrice(line: PurchasePriceDraft): void {
  if (line.pricing_mode === 'total') line.unit_price = purchasePrice(line.quantity, 'total', line.line_total)
  else line.line_total = purchasePrice(line.quantity, 'unit_price', line.unit_price)
}
export function editPurchasePrice(line: PurchasePriceDraft, field: 'unit_price' | 'line_total', value: string): void {
  // 最后编辑的价格字段就是计算依据，用户无需选择算法；数量变化仍沿用这个依据。
  line.pricing_mode = field === 'line_total' ? 'total' : 'unit_price'
  line[field] = value
  recalculatePurchasePrice(line)
  // 两项价格都清空时，申请回到未定价状态；订单的必填仍由输入及服务端检查。
  if (value === '') line.pricing_mode = 'unit_price'
}
export function newPurchasePriceLine() {
  return { material_id: 0, quantity: '1', pricing_mode: 'unit_price' as PurchasePricingMode, unit_price: '', line_total: '' }
}
export function purchasePricePayload(line: PurchasePriceDraft) {
  // 仅提交计价依据，派生值由服务端重算；空价格申请兼容历史及 MRP 来源。
  return line.pricing_mode === 'total'
    ? { pricing_mode: line.pricing_mode, line_total: line.line_total }
    : { pricing_mode: line.pricing_mode, ...(line.unit_price !== '' ? { unit_price: line.unit_price } : {}) }
}
export function restorePurchasePrice(line: {quantity: string; unit_price?: string | null;
  line_total?: string | null; pricing_mode?: PurchasePricingMode}): PurchasePriceDraft {
  const draft = { quantity: line.quantity, unit_price: line.unit_price ?? '',
    line_total: line.line_total ?? '', pricing_mode: line.pricing_mode ?? 'unit_price' }
  recalculatePurchasePrice(draft)
  return draft
}
export function proratePurchaseTotal(total: string, sourceQuantity: string, quantity: string): string {
  const amount = scaled(total, 2), original = scaled(sourceQuantity, 3), count = scaled(quantity, 3)
  if (amount === null || original === null || original <= 0n || count === null) return ''
  return decimal(rounded(amount * count, original), 2)
}
