// 用途是产品独立开关；缺字段兼容旧服务，最终写入仍由服务端校验。
export const materialUseLabels = { can_sell: '销售', can_purchase: '采购', can_produce: '生产' } as const
export type MaterialUse = keyof typeof materialUseLabels
export type MaterialUses = Partial<Record<MaterialUse, boolean>>

export function validateMaterialUses(row: Record<string, unknown>): void {
  for (const key of Object.keys(materialUseLabels)) {
    if (row[key] !== undefined && typeof row[key] !== 'boolean') throw new Error('物料业务用途响应无效')
  }
}
