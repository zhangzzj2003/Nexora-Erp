import type { MaterialCategory, MaterialChoice, MaterialDetails } from '../../../shared/material-api'
import type { WorkspaceSelectOption } from './workspace-select'

// 展示和搜索共用字段清单，不解析自由文本，也不推断替代料或单位换算。
export const materialCoreFields = [
  ['category_name', '分类'], ['specification', '规格型号'], ['package', '封装'],
  ['brand', '品牌'], ['manufacturer_part_number', '制造商料号'], ['unit', '单位']
] as const
export const materialTechnicalFields = [
  ['electrical_value', '标称参数'], ['tolerance', '公差'], ['rated_voltage', '额定电压'],
  ['rated_power', '额定功率'], ['temperature_range', '温度范围'], ['compliance', '合规信息'], ['notes', '备注']
] as const
const detailKeys: readonly (keyof MaterialDetails)[] = ['category_code', 'specification', 'package', 'brand',
  'manufacturer_part_number', ...materialTechnicalFields.map(([key]) => key)]

export function materialChoiceCategory(item: MaterialChoice, categories: readonly MaterialCategory[]): string {
  if (item.category_name?.trim()) return item.category_name.trim()
  if (item.category_code === '') return '未分类'
  for (const group of categories) {
    const child = group.children.find(entry => entry.code === item.category_code)
    if (child) return `${group.name} / ${child.name}`
  }
  return '分类资料暂不可用'
}
export function hasMaterialDetails(item: MaterialChoice): boolean {
  return !!item.spec_values?.length || detailKeys.some(key => typeof item[key] === 'string')
}
export function materialChoiceFacts(item: MaterialChoice, categories: readonly MaterialCategory[], technical = false) {
  const facts: {key: string; label: string; value: string}[] = (technical ? materialTechnicalFields : materialCoreFields).map(([key, label]) => ({
    key, label, value: (key === 'category_name' ? materialChoiceCategory(item, categories) : item[key])?.trim() || '未填写'
  }))
  if (technical) {
    for (const entry of item.spec_values ?? []) facts.push({key:`spec:${entry.field_id}`, label:`${entry.name}${entry.historical ? '（历史）' : ''}`,
      value: entry.status === 'filled' ? `${typeof entry.value === 'boolean' ? entry.value ? '是' : '否' : entry.value}${entry.unit}` : ({unknown:'未知',not_applicable:'不适用',pending:'待确认'} as const)[entry.status]})
    for (const [index, entry] of (item.extra_attributes ?? []).entries()) facts.push({key:`extra:${index}`,label:entry.name,value:entry.value + entry.unit})
  } else if (item.spec_summary) facts.push({key:'spec_summary', label:'分类规格', value:item.spec_summary})
  return facts
}
export interface MaterialSelectOption<T extends number | null> extends WorkspaceSelectOption<T> {
  description: string
  searchText: string
}
export function materialSelectOptions<T extends number | null>(options: readonly WorkspaceSelectOption<T>[],
  materials: readonly MaterialChoice[], categories: readonly MaterialCategory[]): MaterialSelectOption<T>[] {
  const indexed = new Map(materials.map(item => [item.id, item]))
  // 仅丰富调用方已有选项，不扩充候选集合，保留“全部”、历史来源及业务禁用条件。
  return options.map(option => {
    const item = option.value === null ? undefined : indexed.get(option.value)
    return { ...option,
      label: item ? `${item.sku} · ${item.name}` : option.label,
      description: item ? [item.spec_summary, item.specification, item.package, item.brand, item.manufacturer_part_number]
        .filter(value => value?.trim()).join(' · ') || (hasMaterialDetails(item) ? '规格、封装、品牌和料号未填写' : '详细资料暂不可用') : '',
      searchText: [option.label, item?.sku, item?.name, item?.unit,
        ...(item ? [item.spec_summary, ...(item.spec_values ?? []).flatMap(entry => [entry.name, entry.value, entry.unit]), ...(item.extra_attributes ?? []).flatMap(entry => [entry.name, entry.value, entry.unit]), materialChoiceCategory(item, categories), ...detailKeys.map(key => item[key])] : [])]
        .filter(value => typeof value === 'string').join(' ').toLowerCase()
    }
  })
}
export function matchesMaterialChoice(query: string, searchText: string): boolean {
  // 多个关键词可分别命中规格和封装，百分号等符号仍按字面匹配。
  return query.trim().toLowerCase().split(/\s+/).every(word => searchText.includes(word))
}
