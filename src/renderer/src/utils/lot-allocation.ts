import { receiptLotMilli } from '../../../shared/receipt-lot-api.ts'

// 汇总只用于界面核对，不替代各单据的可用量、日期和权限校验。
export interface LotEditorPart {
  quantity: string
  lot_id?: number | null
  supplier_lot?: string | null
  manufactured_on?: string | null
  expires_on?: string | null
}

function formatMilli(value: bigint): string {
  const sign = value < 0n ? '-' : ''
  const absolute = value < 0n ? -value : value
  const fraction = (absolute % 1000n).toString().padStart(3, '0').replace(/0+$/, '')
  return `${sign}${absolute / 1000n}${fraction ? `.${fraction}` : ''}`
}

export function lotAllocation(expected: string, parts: readonly LotEditorPart[], allowEmpty = false) {
  // 盘亏和负调整按差异绝对量分配；用整数千分位避免小数相加误报差额。
  const source = expected.replace(/^-/, '')
  const target = /^\d{1,15}(?:\.\d{1,3})?$/.test(source)
    ? BigInt(source.split('.')[0]) * 1000n + BigInt((source.split('.')[1] ?? '').padEnd(3, '0')) : null
  let total = 0n
  // 分批入库允许某行本次不收货；其他单据仍保留至少一批的原约束。
  let valid = target !== null && (allowEmpty || parts.length > 0)
  for (const part of parts) {
    const quantity = receiptLotMilli(part.quantity)
    if (quantity === null) valid = false
    else total += quantity
  }
  const remaining = target === null ? null : target - total
  return {
    expected: target === null ? '—' : formatMilli(target), allocated: formatMilli(total),
    remaining: valid && remaining !== null ? formatMilli(remaining < 0n ? -remaining : remaining) : '—',
    status: !valid ? 'invalid' : remaining === 0n ? 'complete' : remaining! < 0n ? 'over' : 'incomplete'
  }
}
