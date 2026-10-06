import type { MaterialUnit } from '../../../../../shared/material-unit-api'

// 停用单位仅保留当前物料原值；其他物料和新增档案不能选择它。
export function materialUnitOptions(units: readonly MaterialUnit[], current: string, editing: boolean) {
  return units.filter(unit => unit.enabled || (editing && unit.name === current)).map(unit => ({
    value: unit.name, label: unit.enabled ? unit.name : `${unit.name}（已停用，保留原单位）`
  }))
}
export function defaultMaterialUnit(units: readonly MaterialUnit[]): string {
  return units.find(unit => unit.enabled && unit.name === '件')?.name || units.find(unit => unit.enabled)?.name || ''
}
