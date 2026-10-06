import type { MaterialSummary } from '../../../shared/material-api'
import { receiptLotMilli } from '../../../shared/receipt-lot-api.ts'

export interface DocumentMaterialLine { material_id: number; quantity: string }
// 单据接口最多接收一百项物料，新增行与保存校验使用同一上限。
export const documentMaterialLimit = 100

// 新行立即进入草稿，编号留空等待行内搜索；保留已有行对象，删除中间行不会错配输入。
export function appendDocumentMaterialRow(lines: readonly DocumentMaterialLine[]): DocumentMaterialLine[] {
  return lines.length >= documentMaterialLimit ? [...lines] : [...lines, { material_id: 0, quantity: '1' }]
}
export function documentMaterialDisabled(lines: readonly DocumentMaterialLine[], index: number, materialId: number): boolean {
  return lines.some((line, rowIndex) => rowIndex !== index && line.material_id === materialId)
}

// 按服务端支持的数量范围校验，避免小数精度被浮点转换悄悄截断。
export function documentMaterialIssue(lines: readonly DocumentMaterialLine[], materials: readonly MaterialSummary[]): string {
  if (!lines.length) return '请至少添加一项物料。'
  if (lines.length > documentMaterialLimit) return '每张单据最多添加 100 项物料。'
  const selected = new Set<number>()
  for (const [index, line] of lines.entries()) {
    const prefix = `第 ${index + 1} 行：`
    if (!line.material_id) return `${prefix}请选择物料。`
    if (!materials.some(material => material.id === line.material_id)) return `${prefix}物料已不可用，请重新选择或移除。`
    if (selected.has(line.material_id)) return `${prefix}同一物料只能添加一次，请修改数量或重新选择。`
    if (receiptLotMilli(line.quantity) === null) return `${prefix}数量须大于零、最多三位小数且不超过一百万。`
    selected.add(line.material_id)
  }
  return ''
}

export function appendDocumentMaterial(lines: readonly DocumentMaterialLine[], draft: DocumentMaterialLine,
  materials: readonly MaterialSummary[]): { lines: DocumentMaterialLine[]; issue: string } {
  const issue = (lines.length >= documentMaterialLimit ? '每张单据最多添加 100 项物料。' : '')
    || documentMaterialIssue([draft], materials)
    || (lines.some(line => line.material_id === draft.material_id) ? '该物料已添加，请直接修改表格中的数量。' : '')
  // 失败不改动已有草稿，成功时复制输入，避免选择区后续编辑影响已加入的行。
  return { lines: issue ? [...lines] : [...lines, { ...draft }], issue }
}
