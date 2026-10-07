import type { MaterialCategoryNode, MaterialSpecField } from './material-api'

// 所有动态字段仍经过固定 IPC 白名单，不能把类别短码当成任意 URL。
const kinds = ['text', 'number', 'enum', 'boolean', 'date']
const statuses = ['filled', 'unknown', 'not_applicable', 'pending']
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('物料分类或规格格式无效')
  return value as Record<string, unknown>
}
function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}
function order(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 9999
}
function text(value: unknown, limit: number, required = false): value is string {
  return typeof value === 'string' && value.length <= limit && (!required || !!value.trim())
}
export function materialCategoryCode(payload: unknown): string {
  const code = object(payload).code
  if (typeof code !== 'string' || !/^[A-Z]{2,4}(?:-[A-Z]{2,4})?$/.test(code)) throw new Error('物料分类短码无效')
  return code
}
export function materialCategoryRevision(payload: unknown): {version: number; reason: string} {
  const input = object(payload)
  if (!positive(input.version) || !text(input.reason, 500, true)) throw new Error('请刷新分类版本并填写修改原因')
  return {version: input.version, reason: input.reason.trim()}
}
export function materialCategoryBody(payload: unknown, editing: boolean): Record<string, unknown> {
  const input = object(payload), code = materialCategoryCode(payload)
  if (!text(input.name, 80, true) || !text(input.notes, 500) || typeof input.enabled !== 'boolean'
    || !order(input.sort_order) || (input.parent_code !== null && !text(input.parent_code, 4, true))) throw new Error('物料分类字段无效')
  if (input.parent_code === null ? code.includes('-') : !new RegExp(`^${input.parent_code}-[A-Z]{2,4}$`).test(code)
    || !/^[A-Z]{2,4}$/.test(input.parent_code as string)) throw new Error('物料分类层级无效')
  return {code, parent_code: input.parent_code, name: input.name.trim(), notes: input.notes.trim(),
    enabled: input.enabled, sort_order: input.sort_order, ...(editing ? materialCategoryRevision(input) : {})}
}
export function materialSpecFieldBody(payload: unknown): Record<string, unknown> {
  const input = object(payload)
  if (!text(input.name, 80, true) || !kinds.includes(input.kind as string) || !text(input.unit, 20)
    || !Array.isArray(input.options) || input.options.length > 50
    || input.options.some(value => !text(value, 120, true)) || new Set(input.options.map(value => value.trim())).size !== input.options.length
    || ['required', 'enabled', 'allow_custom'].some(key => typeof input[key] !== 'boolean') || !order(input.sort_order)) {
    throw new Error('规格字段配置无效')
  }
  if (input.kind !== 'number' && input.unit || input.kind !== 'enum' && (input.allow_custom || input.options.length)
    || input.kind === 'enum' && !input.options.length && !input.allow_custom) throw new Error('规格类型、单位或选项不匹配')
  return {...materialCategoryRevision(input), name: input.name.trim(), kind: input.kind, unit: input.unit.trim(),
    options: input.options.map(value => value.trim()), required: input.required, enabled: input.enabled,
    allow_custom: input.allow_custom, sort_order: input.sort_order}
}
export function materialSpecBody(payload: unknown, valueLimit = 50): Record<string, unknown> {
  const input = object(payload), body: Record<string, unknown> = {}
  if (input.spec_values !== undefined) {
    if (!Array.isArray(input.spec_values) || input.spec_values.length > valueLimit || !positive(input.spec_template_version)) throw new Error('物料规格或模板版本无效')
    const ids = new Set<number>()
    body.spec_values = input.spec_values.map(raw => {
      const entry = object(raw)
      if (!positive(entry.field_id) || ids.has(entry.field_id) || !statuses.includes(entry.status as string)
        || !(entry.value === null || typeof entry.value === 'boolean' || text(entry.value, 500))
        || !text(entry.source, 500)) throw new Error('物料规格值无效')
      if (entry.status !== 'filled' && entry.value !== null && entry.value !== '') throw new Error('未知规格不能同时填写数值')
      ids.add(entry.field_id)
      return {field_id: entry.field_id, status: entry.status, value: entry.value, source: entry.source.trim()}
    })
    body.spec_template_version = input.spec_template_version
  }
  if (input.extra_attributes !== undefined) {
    if (!Array.isArray(input.extra_attributes) || input.extra_attributes.length > 20) throw new Error('物料扩展属性数量无效')
    const names = new Set<string>()
    body.extra_attributes = input.extra_attributes.map(raw => {
      const entry = object(raw)
      if (!text(entry.name, 80, true) || !text(entry.value, 500, true) || !text(entry.unit, 20)
        || names.has(entry.name.trim())) throw new Error('物料扩展属性无效或重复')
      names.add(entry.name.trim())
      return {name: entry.name.trim(), value: entry.value.trim(), unit: entry.unit.trim()}
    })
  }
  return body
}
function validateField(raw: unknown, category: string): MaterialSpecField {
  const field = object(raw)
  if (!positive(field.id) || field.category_code !== category || !text(field.name, 80, true)
    || !kinds.includes(field.kind as string) || !text(field.unit, 20) || !order(field.sort_order)
    || ['required', 'enabled', 'allow_custom', 'deleted', 'used'].some(key => typeof field[key] !== 'boolean')
    || !Array.isArray(field.options) || field.options.length > 50 || field.options.some(value => !text(value, 120, true))) throw new Error('物料规格模板响应无效')
  return field as unknown as MaterialSpecField
}
function validateNode(raw: unknown): MaterialCategoryNode {
  const node = object(raw)
  materialCategoryCode(node)
  if (!text(node.name, 80, true) || !text(node.notes, 500) || !positive(node.version) || !positive(node.template_version)
    || !order(node.sort_order) || !Number.isSafeInteger(node.material_count) || (node.material_count as number) < 0
    || ['enabled', 'deleted', 'used'].some(key => typeof node[key] !== 'boolean')
    || !Array.isArray(node.fields) || node.fields.length > 50
    || (node.parent_code !== null && (!text(node.parent_code, 4, true) || !/^[A-Z]{2,4}$/.test(node.parent_code)))) throw new Error('物料分类响应缺少版本或模板，请升级 ERP 服务')
  const ids = new Set<number>()
  for (const rawField of node.fields) {
    const field = validateField(rawField, node.code as string)
    if (ids.has(field.id)) throw new Error('物料规格模板字段重复')
    ids.add(field.id)
  }
  return node as unknown as MaterialCategoryNode
}
export function validateMaterialCategoryResult(action: string, value: unknown): void {
  if (action === 'materialCategories') {
    if (!Array.isArray(value)) throw new Error('物料分类响应格式无效')
    // 基础目录的旧契约由原验证器检查；有版本时必须同时包含完整模板。
    for (const raw of value) {
      const group = object(raw)
      if (group.version !== undefined) validateNode(group)
      if (Array.isArray(group.children)) for (const child of group.children) if (object(child).version !== undefined) validateNode(child)
    }
  } else if (action === 'materialCategoryChanges') {
    if (!Array.isArray(value) || value.length > 100) throw new Error('物料分类变更响应无效')
    for (const raw of value) {
      const row = object(raw)
      if (!positive(row.id) || !text(row.reason, 500, true) || !text(row.changed_by_name, 120, true)
        || !text(row.created_at, 50, true) || !text(row.action, 40, true)) throw new Error('物料分类变更响应无效')
      materialCategoryCode({code: row.category_code})
      validateNode(row.after)
      if (row.before !== null) validateNode(row.before)
    }
  } else if (['createMaterialCategory', 'updateMaterialCategory', 'deleteMaterialCategory',
    'createMaterialSpecField', 'updateMaterialSpecField', 'deleteMaterialSpecField'].includes(action)) validateNode(value)
}
export function validateMaterialSpecs(raw: unknown): void {
  const row = object(raw)
  if (row.spec_values !== undefined) {
    materialSpecBody({spec_values: row.spec_values, spec_template_version: row.spec_template_version}, 500)
    for (const rawEntry of row.spec_values as unknown[]) {
      const entry = object(rawEntry)
      if (!text(entry.name, 80, true) || !text(entry.unit, 20) || !kinds.includes(entry.kind as string)
        || !text(entry.category_code, 10, true) || typeof entry.historical !== 'boolean') throw new Error('物料规格响应无效')
    }
    if (!text(row.spec_summary, 40000)) throw new Error('物料规格摘要响应无效')
  }
  if (row.extra_attributes !== undefined) materialSpecBody({extra_attributes: row.extra_attributes})
}
