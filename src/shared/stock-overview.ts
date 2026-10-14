import type { StockPageResult, StockOverviewItem } from './erp-api'

// 服务端升级前不能把缺少分类、全仓分布或统计的数据误显示为零库存。
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
// Decimal 对很小的数量可能返回指数形式，同样保留字符串精度并拒绝 NaN/Infinity。
const quantity = (value: unknown): value is string => typeof value === 'string' && /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value)
const positiveId = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0
export function isStockOverviewItem(value: unknown): value is StockOverviewItem {
  if (!record(value) || !positiveId(value.id) || !['sku', 'name', 'unit', 'category_code', 'category_name', 'category_group_name']
    .every(key => typeof value[key] === 'string') || !quantity(value.quantity) || !quantity(value.total_quantity) || !Array.isArray(value.warehouses)) return false
  const ids = new Set<number>()
  return value.warehouses.every(row => {
    if (!record(row) || !positiveId(row.warehouse_id) || ids.has(Number(row.warehouse_id))
      || typeof row.warehouse_name !== 'string' || typeof row.warehouse_code !== 'string' || !quantity(row.quantity)) return false
    ids.add(Number(row.warehouse_id)); return true
  })
}
export function validateStockOverview(value: unknown): asserts value is StockPageResult {
  if (!record(value) || !Array.isArray(value.items) || !value.items.every(isStockOverviewItem)
    || !positiveId(value.page) || !positiveId(value.page_size) || Number(value.page_size) > 100
    || !Number.isSafeInteger(value.total) || Number(value.total) < 0 || !record(value.summary)
    || !['material_count', 'positive_material_count', 'zero_material_count', 'negative_material_count']
      .every(key => Number.isSafeInteger(value.summary && (value.summary as Record<string, unknown>)[key])
        && Number((value.summary as Record<string, unknown>)[key]) >= 0)) {
    throw Error('库存总览数据不完整，请升级服务端后重新查询。')
  }
  const counts = value.summary
  if (counts.material_count !== value.total || Number(counts.positive_material_count) + Number(counts.zero_material_count)
    + Number(counts.negative_material_count) !== value.total || value.items.length > Number(value.page_size)) {
    throw Error('库存总览统计范围不一致，请重新查询。')
  }
}

// 只判断符号，不将精确数量转为 JavaScript 浮点数；负零不提示异常。
export function isNegativeStock(value: string): boolean {
  return value.startsWith('-') && /[1-9]/.test(value.split(/[eE]/)[0])
}
