export interface InventoryWarningNotice {
  outOfStock: number
  low: number
}

export function validateInventoryWarningNotice(value: unknown): InventoryWarningNotice {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('库存预警通知参数无效')
  const input = value as Record<string, unknown>
  const valid = (count: unknown): count is number =>
    typeof count === 'number' && Number.isSafeInteger(count) && count >= 0 && count <= 10_000
  if (!valid(input.outOfStock) || !valid(input.low) || input.outOfStock + input.low === 0)
    throw new Error('库存预警通知参数无效')
  return { outOfStock: input.outOfStock, low: input.low }
}

export function inventoryWarningNoticeBody(notice: InventoryWarningNotice): string {
  const counts = [notice.outOfStock && `缺货 ${notice.outOfStock} 项`,
    notice.low && `低库存 ${notice.low} 项`].filter(Boolean).join('、')
  // 系统通知可能出现在锁屏上，仅展示数量，物料和仓库详情留在登录后的应用内。
  return `${counts}。请打开 Nexora ERP 查看库存预警。`
}
