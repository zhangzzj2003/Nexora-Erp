import type { Material, MaterialCategory, MaterialDetails, MaterialInput } from '../../../../../shared/material-api'

// 草稿的大类只用于选择联动，实际接口提交经过目录验证的子类代码。
export interface MaterialDraft extends MaterialDetails {
  sku: string
  name: string
  unit: string
  group_code: string
  version?: number
  reason: string
}
export function materialDraft(item?: Material): MaterialDraft {
  return {
    sku: item?.sku ?? '', name: item?.name ?? '', unit: item?.unit ?? '件',
    category_code: item?.category_code ?? '', group_code: item?.category_code.split('-')[0] || 'EL',
    specification: item?.specification ?? '', package: item?.package ?? '', brand: item?.brand ?? '',
    manufacturer_part_number: item?.manufacturer_part_number ?? '', electrical_value: item?.electrical_value ?? '',
    tolerance: item?.tolerance ?? '', rated_voltage: item?.rated_voltage ?? '', rated_power: item?.rated_power ?? '',
    temperature_range: item?.temperature_range ?? '', compliance: item?.compliance ?? '', notes: item?.notes ?? '',
    version: item?.version, reason: ''
  }
}
export function materialInput(draft: MaterialDraft, editing: boolean): MaterialInput {
  // 白名单避免把表格的 UI 字段或仅用于联动的大类写进服务端。
  return {
    ...(editing ? { sku: draft.sku, version: draft.version } : {}),
    name: draft.name, unit: draft.unit, category_code: draft.category_code,
    specification: draft.specification, package: draft.package, brand: draft.brand,
    manufacturer_part_number: draft.manufacturer_part_number, electrical_value: draft.electrical_value,
    tolerance: draft.tolerance, rated_voltage: draft.rated_voltage, rated_power: draft.rated_power,
    temperature_range: draft.temperature_range, compliance: draft.compliance, notes: draft.notes,
    reason: draft.reason
  }
}
export function materialCategoryLabel(code: string, categories: MaterialCategory[]): string {
  for (const group of categories) {
    const child = group.children.find(item => item.code === code)
    if (child) return `${group.name} / ${child.name}`
  }
  return '未分类'
}
export function matchesMaterial(item: Material, query: string, category: string, categories: MaterialCategory[]): boolean {
  // 搜索包含独立规格、封装及制造商料号，仍按字面子串匹配。
  if (category === 'unclassified' ? !!item.category_code : category && item.category_code !== category) return false
  return [item.sku, item.name, item.unit, item.specification, item.package, item.brand,
    item.manufacturer_part_number, item.electrical_value, item.tolerance, item.rated_voltage,
    item.rated_power, item.temperature_range, item.compliance, item.notes,
    materialCategoryLabel(item.category_code, categories)].join(' ').toLowerCase().includes(query.trim().toLowerCase())
}
