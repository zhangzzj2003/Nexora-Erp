// 数量保留十进制字符串，当前采购供需与历史单据数量分别展示。
export const materialSupplyPhases = ['stock', 'planned', 'awaiting_delivery', 'awaiting_inbound'] as const
export type MaterialSupplyPhase = typeof materialSupplyPhases[number]
export const materialSupplyLabels: Record<MaterialSupplyPhase, string> = {
  stock: '库存', planned: '计划中', awaiting_delivery: '待回料', awaiting_inbound: '待入库'
}
export const materialSupplyKindLabels = {
  warehouse: '仓库结存', purchase_request: '采购申请', purchase_order: '采购订单',
  receipt: '采购入库单', mrp_plan: '物料计划'
} as const
export interface MaterialSupplySource {
  phase: MaterialSupplyPhase
  kind: keyof typeof materialSupplyKindLabels
  document_id: number
  document_no: string | null
  reference: string
  quantity: string
  warehouse_name: string | null
}
export interface MaterialSupplyRow {
  material_id: number; sku: string; name: string; unit: string
  stock_quantity: string | null; planned_quantity: string | null
  awaiting_delivery_quantity: string | null; awaiting_inbound_quantity: string | null
  sources: MaterialSupplySource[]
}
export interface MaterialSupplyResult {
  scope: 'all_warehouses'; generated_at: string; rows: MaterialSupplyRow[]
}
export interface MaterialSupplyOperations {
  materialSupply: { input: { material_ids: number[] }; output: MaterialSupplyResult }
}
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const positiveId = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0
const decimal = (value: unknown, signed = false): value is string =>
  typeof value === 'string' && value.length <= 40 && (signed ? /^-?\d+\.\d{3}$/ : /^\d+\.\d{3}$/).test(value)
function invalid(): never { throw Error('物料供需响应格式不匹配，请更新服务端后重试。') }
const milli = (value: string): bigint => BigInt(value.replace('.', ''))

export function materialSupplyBody(value: unknown): { material_ids: number[] } {
  if (!object(value) || !Array.isArray(value.material_ids) || !value.material_ids.length
    || value.material_ids.length > 100 || !value.material_ids.every(positiveId)
    || new Set(value.material_ids).size !== value.material_ids.length) throw Error('物料供需查询编号无效')
  // 仅转发固定编号列表，不允许页面自行指定权限或统计结果。
  return { material_ids: [...value.material_ids] }
}

export function validateMaterialSupply(value: unknown, ids: readonly number[]): asserts value is MaterialSupplyResult {
  if (!object(value) || value.scope !== 'all_warehouses' || typeof value.generated_at !== 'string'
    || !Number.isFinite(Date.parse(value.generated_at)) || !Array.isArray(value.rows) || value.rows.length !== ids.length) invalid()
  for (const [index, row] of value.rows.entries()) {
    if (!object(row) || row.material_id !== ids[index] || !['sku', 'name', 'unit'].every(key => typeof row[key] === 'string')
      || !Array.isArray(row.sources)) invalid()
    const totals = {stock: 0n, planned: 0n, awaiting_delivery: 0n, awaiting_inbound: 0n}
    for (const source of row.sources) {
      if (!object(source) || !materialSupplyPhases.includes(source.phase as MaterialSupplyPhase)
        || !Object.hasOwn(materialSupplyKindLabels, String(source.kind)) || !positiveId(source.document_id)
        || !(source.document_no === null || typeof source.document_no === 'string') || typeof source.reference !== 'string'
        || !(source.warehouse_name === null || typeof source.warehouse_name === 'string')
        || !decimal(source.quantity, source.phase === 'stock')) invalid()
      const phase = source.phase as MaterialSupplyPhase
      if (row[`${phase}_quantity`] === null) invalid()
      totals[phase] += milli(source.quantity)
    }
    // 来源与汇总必须守恒，无权限字段不能携带隐藏证据；精确校验避免浮点尾差。
    for (const phase of materialSupplyPhases) {
      const count = row[`${phase}_quantity`]
      if (count !== null && (!decimal(count, phase === 'stock') || milli(count) !== totals[phase])) invalid()
    }
  }
}
