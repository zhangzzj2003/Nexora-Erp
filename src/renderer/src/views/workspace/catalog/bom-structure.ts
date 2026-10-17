import type { Bom } from '../../../../../shared/erp-api'
import type { MaterialChoice } from '../../../../../shared/material-api'
import { receiptLotMilli } from '../../../../../shared/receipt-lot-api.ts'

export interface BomStructureRow {
  key: string; depth: number; materialId: number; sku: string; name: string; unit: string; quantity: string
  childBom: Bom | null; fixed: boolean; expanded: boolean; issue: string
  // 参数属于本层组件的物料，不能使用下层 BOM 的产出名称或其他行的资料。
  material?: MaterialChoice
}

// 展开仅用于查看结构：整机实际领用的是第一层组件，不再次扣减板内的原材料。
export function bomStructureRows(root: Bom, catalog: readonly Bom[], expanded: ReadonlySet<string>): BomStructureRow[] {
  const byId = new Map(catalog.map(bom => [bom.id, bom]))
  const active = new Map(catalog.filter(bom => bom.status === 'active').map(bom => [bom.product_material_id, bom]))
  const result: BomStructureRow[] = []
  function visit(bom: Bom, prefix: string, depth: number, numerator: bigint, denominator: bigint, path: ReadonlySet<number>): void {
    for (const line of bom.lines) {
      if (result.length >= 1000) {
        result[result.length - 1].issue = '结构超过 1000 行，停止展开，请分支查看'
        return
      }
      const key = `${prefix}/${line.id}`
      const fixed = !!line.component_bom_id
      const child = fixed ? byId.get(line.component_bom_id!) : active.get(line.component_material_id)
      const amount = receiptLotMilli(line.quantity)
      const childBase = child ? receiptLotMilli(child.base_quantity) : null
      const valid = child?.product_material_id === line.component_material_id
      const cycle = path.has(line.component_material_id)
      const issue = cycle ? '存在循环引用' : depth >= 20 ? '超过 20 层，停止展开'
        : fixed && !valid ? '固定版本未加载或与组件不匹配' : fixed && child?.status !== 'active' ? '固定版本已停用，生产前须修订' : ''
      // 千分位整数和分数累计，避免多层换算经过浮点数后出现数量漂移。
      const milli = amount === null ? null : (amount * numerator + denominator - 1n) / denominator
      const quantity = milli === null ? '—' : `${milli / 1000n}.${String(milli % 1000n).padStart(3, '0')}`
      // 明细行号与物料身份不同，详情入口始终保留当前层组件的真实物料 ID。
      result.push({key, depth, materialId:line.component_material_id, sku:line.sku, name:line.material_name, unit:line.unit, quantity,
        childBom:valid ? child! : null, fixed, expanded:expanded.has(key), issue,
        material:line.material?.id === line.component_material_id ? line.material : undefined})
      if (valid && child && amount !== null && childBase !== null && !cycle && depth < 20 && expanded.has(key)) {
        visit(child, key, depth + 1, numerator * amount, denominator * childBase,
          new Set([...path, line.component_material_id]))
      }
    }
  }
  visit(root, String(root.id), 0, 1n, 1n, new Set([root.product_material_id]))
  return result
}
