import type { MaterialChoice } from '../../../../../shared/material-api'
import { receiptLotMilli } from '../../../../../shared/receipt-lot-api.ts'
import { documentMaterialIssue } from '../../../utils/document-material-lines.ts'

interface BomDraft {
  product_material_id: number
  base_quantity: string
  note: string
  lines: { component_material_id: number; quantity: string }[]
}

// 复用物料明细校验，并补上 BOM 的成品与自身引用约束；切换成品时保留原草稿供修正。
export function bomDraftIssue(draft: BomDraft, materials: readonly MaterialChoice[]): string {
  if (!materials.some(item => item.id === draft.product_material_id)) return '请选择可用的成品物料。'
  if (receiptLotMilli(draft.base_quantity) === null) return '基准产出数量须大于零、最多三位小数且不超过一百万。'
  if (draft.note.length > 200) return '版本说明不能超过 200 字。'
  if (draft.lines.some(line => line.component_material_id === draft.product_material_id)) return '成品不能直接作为自身组件，请重新选择组件。'
  return documentMaterialIssue(draft.lines.map(line => ({ material_id: line.component_material_id, quantity: line.quantity })), materials)
}

// 当前行仍可显示自己的物料，其他行已用组件与成品禁选，避免无意重复或自引用。
export function bomComponentOptions(draft: BomDraft, materials: readonly MaterialChoice[], index: number) {
  return materials.map(item => ({ value: item.id, label: `${item.sku} · ${item.name}`,
    disabled: item.id === draft.product_material_id || draft.lines.some((line, other) => other !== index && line.component_material_id === item.id)
  }))
}
