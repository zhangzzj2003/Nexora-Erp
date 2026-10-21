import type { ProductionPlanDetail, ProductionPlanLine } from '../../../../../shared/production-plan-api'

export interface ProductionDemandSource { plan: ProductionPlanDetail; line: ProductionPlanLine }
export interface ProductionDemandVariant {
  key: string; requirements: string; quantity: string; sources: ProductionDemandSource[]
}
export interface ProductionDemandGroup {
  key: string; sku: string; name: string; unit: string; quantity: string; variants: ProductionDemandVariant[]
}
// 千分位整数累加，避免跨计划的小数数量在汇总时产生浮点尾差。
const thousandths = (value: string): number => {
  const [whole, fraction = ''] = value.split('.')
  return Number(whole) * 1000 + Number(fraction.padEnd(3, '0'))
}
export function groupProductionDemands(plans: readonly ProductionPlanDetail[]): ProductionDemandGroup[] {
  const groups = new Map<string, ProductionDemandGroup>()
  for (const plan of plans) {
    if (plan.status === 'cancelled' || !['approved', 'executed'].includes(plan.approval.status)) continue
    for (const line of plan.lines) {
      if (Number(line.unreleased_quantity) <= 0) continue
      // 按物料身份和单位汇总，不按可能重名的产品名称合并。
      const key = JSON.stringify([line.material_id, line.unit])
      let group = groups.get(key)
      if (!group) {
        group = { key, sku: line.sku, name: line.name, unit: line.unit, quantity: '0.000', variants: [] }
        groups.set(key, group)
      }
      const requirements = line.production_requirements?.trim() ?? ''
      // 空要求不表示相同；BOM 和仓库不同也独立列出，所有来源始终分别建单。
      const variantKey = JSON.stringify([line.bom_id, line.warehouse_id, requirements || ['unknown', plan.id, line.id]])
      let variant = group.variants.find(item => item.key === variantKey)
      if (!variant) {
        variant = { key: variantKey, requirements, quantity: '0.000', sources: [] }
        group.variants.push(variant)
      }
      variant.sources.push({ plan, line })
      variant.quantity = ((thousandths(variant.quantity) + thousandths(line.unreleased_quantity)) / 1000).toFixed(3)
      group.quantity = ((thousandths(group.quantity) + thousandths(line.unreleased_quantity)) / 1000).toFixed(3)
    }
  }
  return [...groups.values()]
}
