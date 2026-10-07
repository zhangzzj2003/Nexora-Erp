import { supplierSelectionInput } from './supplier-selection.ts'
import type { Material, MaterialCategory, MaterialDetails, MaterialInput, MaterialSpecValueInput, MaterialSpecField, MaterialSpecValue, MaterialExtraAttribute } from '../../../shared/material-api'
import type { MaterialUnit } from '../../../shared/material-unit-api'

// 草稿的大类只用于选择联动，实际接口提交经过目录验证的子类代码。
export interface MaterialDraft extends MaterialDetails {
  sku: string
  name: string
  unit: string
  // 原单位只用于停用后的保留选项，不写入接口。
  original_unit: string
  group_code: string
  version?: number
  reason: string
  supplier_selection: string[]
  original_category: string
  spec_custom: Record<number, boolean>
  spec_drafts: Record<string, MaterialSpecValueInput[]>
  spec_templates: Record<string, {version: number; fields: MaterialSpecField[]}>
  spec_originals: Record<string, string>
  historical_specs: MaterialSpecValue[]
  extra_attributes: MaterialExtraAttribute[]
  original_extras: string
}
export function materialDraft(item?: Material): MaterialDraft {
  return {
    sku: item?.sku ?? '', name: item?.name ?? '', unit: item?.unit ?? '件',
    original_unit: item?.unit ?? '',
    category_code: item?.category_code ?? '', group_code: item?.category_code.split('-')[0] || 'EL',
    specification: item?.specification ?? '', package: item?.package ?? '', brand: item?.brand ?? '',
    manufacturer_part_number: item?.manufacturer_part_number ?? '', electrical_value: item?.electrical_value ?? '',
    tolerance: item?.tolerance ?? '', rated_voltage: item?.rated_voltage ?? '', rated_power: item?.rated_power ?? '',
    temperature_range: item?.temperature_range ?? '', compliance: item?.compliance ?? '', notes: item?.notes ?? '',
    version: item?.version, reason: '', supplier_selection: (item?.supplier_ids ?? []).map(id => `id:${id}`),
    original_category: item?.category_code ?? '', spec_custom: {}, spec_drafts: {}, spec_templates: {}, spec_originals: {},
    historical_specs: (item?.spec_values ?? []).map(value => ({...value})),
    extra_attributes: (item?.extra_attributes ?? []).map(value => ({...value})),
    original_extras: JSON.stringify(item?.extra_attributes ?? [])
  }
}
export function prepareMaterialSpecs(draft: MaterialDraft, categories: readonly MaterialCategory[]): void {
  const category = categories.flatMap(group => group.children).find(child => child.code === draft.category_code)
  if (!category?.template_version || draft.spec_templates[category.code]) return
  // 切换分类时分别保存草稿和模板版本，不按同名字段把两个类别的值互相错配。
  const fields = (category.fields ?? []).filter(field => field.enabled).map(field => ({...field, options: [...field.options]}))
  const original = new Map(draft.historical_specs.filter(entry => entry.category_code === category.code).map(entry => [entry.field_id, entry]))
  draft.spec_templates[category.code] = {version: category.template_version, fields}
  draft.spec_drafts[category.code] = fields.map(field => {
    const value = original.get(field.id)
    draft.spec_custom[field.id] = field.kind === 'enum' && !!value?.value && !field.options.includes(String(value.value))
    return {field_id: field.id, status: value?.status ?? 'unknown', value: value?.value ?? null, source: value?.source ?? ''}
  })
  draft.spec_originals[category.code] = JSON.stringify(draft.spec_drafts[category.code])
}
export function materialInput(draft: MaterialDraft, editing: boolean, units?: readonly MaterialUnit[]): MaterialInput {
  const unit = units?.find(item => item.name === draft.unit)
  if (units && !unit) throw new Error('请从单位目录选择单位，或先到单位管理中新增。')
  if (unit && !unit.enabled && (!editing || draft.unit !== draft.original_unit)) throw new Error('所选单位已停用，请重新选择。')
  // 白名单避免把表格的 UI 字段或仅用于联动的大类写进服务端。
  const template = draft.spec_templates[draft.category_code]
  const values = draft.spec_drafts[draft.category_code] ?? []
  const changedSpecs = !editing || draft.category_code !== draft.original_category || JSON.stringify(values) !== draft.spec_originals[draft.category_code]
  return {
    ...(editing ? { sku: draft.sku, version: draft.version } : {}),
    name: draft.name, unit: draft.unit, category_code: draft.category_code,
    ...(unit ? { unit_id: unit.id } : {}),
    specification: draft.specification, package: draft.package, brand: draft.brand,
    manufacturer_part_number: draft.manufacturer_part_number, electrical_value: draft.electrical_value,
    tolerance: draft.tolerance, rated_voltage: draft.rated_voltage, rated_power: draft.rated_power,
    temperature_range: draft.temperature_range, compliance: draft.compliance, notes: draft.notes,
    reason: draft.reason, suppliers: supplierSelectionInput(draft.supplier_selection),
    // 未修改规格的旧档案不重验新增必填项；主动补规格必须提交当时模板版本。
    ...(template && changedSpecs ? {spec_template_version: template.version, spec_values: values.map(entry => ({...entry}))} : {}),
    ...(!editing || JSON.stringify(draft.extra_attributes) !== draft.original_extras
      ? {extra_attributes: draft.extra_attributes.map(entry => ({...entry}))} : {})
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
    item.rated_power, item.temperature_range, item.compliance, item.notes, item.spec_summary,
    ...(item.spec_values ?? []).flatMap(entry => [entry.name, entry.value, entry.unit, entry.source]),
    ...(item.extra_attributes ?? []).flatMap(entry => [entry.name, entry.value, entry.unit]),
    materialCategoryLabel(item.category_code, categories)].join(' ').toLowerCase().includes(query.trim().toLowerCase())
}
