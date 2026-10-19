import type { MaterialChoice } from '../../../shared/material-api'
import { materialUseLabels, type MaterialUse } from '../../../shared/material-uses.ts'
import type { WorkspaceSelectOption } from './workspace-select'

// 只收窄当前业务的新选料范围；旧草稿仍保留原编号、资料和输入，禁用项明确要求重选。
export function materialUseOptions<T extends number | null>(options: readonly WorkspaceSelectOption<T>[],
  materials: readonly MaterialChoice[], use: MaterialUse | undefined, selected: T): readonly WorkspaceSelectOption<T>[] {
  if (!use) return options
  const blocked = new Set(materials.filter(row => row[use] === false).map(row => row.id))
  return options.flatMap(option => {
    if (option.value === null || !blocked.has(option.value)) return [option]
    return option.value === selected
      ? [{ ...option, disabled: true, label: `${option.label}（不可${materialUseLabels[use]}，请重新选择）` }] : []
  })
}

// 保存前再检查已知限制，覆盖弹窗打开后用途改变；未知物料和旧接口仍交给服务端最终校验。
export function materialUseIssue(lines: readonly { material_id: number }[], materials: readonly MaterialChoice[], use: MaterialUse): string {
  const directory = new Map(materials.map(row => [row.id, row]))
  for (const [index, line] of lines.entries()) {
    const material = directory.get(line.material_id)
    if (material?.[use] === false) return `第 ${index + 1} 行物料 ${material.sku} 未允许${materialUseLabels[use]}，请重新选择或维护产品资料。`
  }
  return ''
}
