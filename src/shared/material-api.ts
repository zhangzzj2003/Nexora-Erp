// 历史单据保留简要契约；业务选料可以附带当前档案的只读资料。
export interface MaterialSummary { id: number; sku: string; name: string; unit: string }
export interface MaterialDetails {
  category_code: string
  specification: string
  package: string
  brand: string
  manufacturer_part_number: string
  electrical_value: string
  tolerance: string
  rated_voltage: string
  rated_power: string
  temperature_range: string
  compliance: string
  notes: string
}
// 可选字段兼容旧业务接口的简要响应，不把未提供的详情当成已填写资料。
export interface MaterialChoice extends MaterialSummary, Partial<MaterialDetails> {
  category_name?: string
  spec_values?: MaterialSpecValue[]
  spec_summary?: string
  extra_attributes?: MaterialExtraAttribute[]
  spec_template_version?: number
}
export interface Material extends MaterialSummary, MaterialDetails {
  category_name?: string
  spec_values?: MaterialSpecValue[]
  spec_summary?: string
  extra_attributes?: MaterialExtraAttribute[]
  spec_template_version?: number
  version: number
  // 编辑专用详情同时返回绑定编号；列表及旧调用继续使用原有简要响应。
  supplier_ids?: number[]
}
export type MaterialSupplierInput = { supplier_id: number; name?: never } | { name: string; supplier_id?: never }
export type MaterialSpecKind = 'text' | 'number' | 'enum' | 'boolean' | 'date'
export type MaterialSpecStatus = 'filled' | 'unknown' | 'not_applicable' | 'pending'
// 字段编号是稳定身份；中文名称可以修订，数值使用字符串保持十进制精度。
export interface MaterialSpecValueInput {
  field_id: number; status: MaterialSpecStatus; value: string | boolean | null; source: string
}
export interface MaterialSpecValue extends MaterialSpecValueInput {
  category_code: string; name: string; kind: MaterialSpecKind; unit: string; historical: boolean
}
export interface MaterialExtraAttribute { name: string; value: string; unit: string }
export interface MaterialSpecField {
  id: number; category_code: string; name: string; kind: MaterialSpecKind; unit: string
  options: string[]; allow_custom: boolean; required: boolean; enabled: boolean
  sort_order: number; used: boolean; deleted: boolean
}
export interface MaterialCategoryNode {
  code: string
  name: string
  parent_code: string | null; enabled: boolean; deleted: boolean; used: boolean
  sort_order: number; notes: string; version: number; template_version: number
  material_count: number; fields: MaterialSpecField[]
}
// 旧服务目录仍可辨认；新增管理能力须具有版本和规格模板。
export interface MaterialCategory extends Partial<MaterialCategoryNode> {
  code: string; name: string
  children: (Partial<MaterialCategoryNode> & {code: string; name: string})[]
}
export interface MaterialCategoryInput {
  code: string; parent_code: string | null; name: string; enabled: boolean
  sort_order: number; notes: string; version?: number; reason?: string
}
export interface MaterialCategoryRevision {code: string; version: number; reason: string}
export interface MaterialSpecFieldInput {
  name: string; kind: MaterialSpecKind; unit: string; options: string[]; allow_custom: boolean
  required: boolean; enabled: boolean; sort_order: number; version: number; reason: string
}
export interface MaterialCategoryChange {
  id: number; category_code: string; action: string; before: MaterialCategoryNode | null
  after: MaterialCategoryNode; reason: string; changed_by_name: string; created_at: string
}
// 新增省略 sku，编辑携带原编码和读取时的版本；可选字段兼容原有调用入口。
export interface MaterialInput extends Partial<MaterialDetails> {
  spec_values?: MaterialSpecValueInput[]
  spec_template_version?: number
  extra_attributes?: MaterialExtraAttribute[]
  sku?: string
  name: string
  unit: string
  // 新客户端提交目录编号，服务端核对名称和启用状态；旧调用可省略。
  unit_id?: number
  version?: number
  reason?: string
  suppliers?: MaterialSupplierInput[]
}
