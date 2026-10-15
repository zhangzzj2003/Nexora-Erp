import { receiptLotMilli } from './receipt-lot-api.ts'
import type { Material, MaterialInput } from './material-api'
import { materialBody, validateMaterialResult } from './material-validation.ts'

// 产品档案只扩展物料，所有业务仍使用 material_id。
export const productKinds = ['finished', 'semi_finished', 'component', 'unclassified'] as const
export type ProductKind = typeof productKinds[number]
export const productKindLabels: Record<ProductKind, string> = {
  finished: '成品', semi_finished: '半成品', component: '组件', unclassified: '待分类'
}
export interface ProductModel { id: number; code: string; name: string; notes: string; version: number; created_by: number; created_at: string }
export interface ProductProfile {
  id: number; material_id: number; kind: ProductKind; model_id: number | null
  configuration_name: string; version: number; created_by: number | null; created_at: string
  model_code: string; model_name: string; material: Material
}
export interface ProductFields { kind: ProductKind; model_id: number | null; configuration_name: string; reason?: string }
export type ProductInput = ProductFields & ({ material_id: number; material?: never } | { material: MaterialInput; material_id?: never })
export type ProductUpdate = ProductFields & { id: number; version: number; reason: string; material?: MaterialInput }
export interface ProductQuery { query: string; kind: ProductKind | null; model_id: number | null; page: number; page_size: number }
export interface ProductPage { items: ProductProfile[]; total: number; page: number; page_size: number }
export interface ProductModelInput { code: string; name: string; notes: string; version?: number; reason?: string }
export interface ProductChange { id: number; before: ProductProfile | ProductModel | null; after: ProductProfile | ProductModel; reason: string; changed_by_name: string; created_at: string }
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error('产品资料格式无效')
  return v as Record<string, unknown>
}
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0
const text = (v: unknown, max: number, required = false): string => {
  if (typeof v !== 'string' || v.length > max || (required && !v.trim())) throw Error('产品字段为空或超出长度限制')
  return v.trim()
}
function modelId(v: unknown): number | null {
  if (v !== null && !positive(v)) throw Error('机型编号无效')
  return v
}
export function productBody(value: unknown, editing: boolean): Record<string, unknown> {
  const input = object(value)
  if (!productKinds.includes(input.kind as ProductKind)) throw Error('产品类型无效')
  const body: Record<string, unknown> = {kind: input.kind, model_id: modelId(input.model_id),
    configuration_name: text(input.configuration_name, 120)}
  if (editing) {
    if (!positive(input.version)) throw Error('请重新读取产品版本')
    body.version = input.version; body.reason = text(input.reason, 500, true)
    if (input.material !== undefined) body.material = materialBody(input.material, true)
  } else {
    if ((input.material_id === undefined) === (input.material === undefined)) throw Error('请选择一种产品建档方式')
    if (input.material_id !== undefined) {
      if (!positive(input.material_id)) throw Error('物料编号无效')
      body.material_id = input.material_id
    } else body.material = materialBody(input.material, false)
    if (input.reason !== undefined) body.reason = text(input.reason, 500)
  }
  return body
}
export function productModelBody(value: unknown, editing: boolean): Record<string, unknown> {
  const input = object(value), body: Record<string, unknown> = {code: text(input.code, 40, true),
    name: text(input.name, 120, true), notes: text(input.notes, 500)}
  if (editing) {
    if (!positive(input.version)) throw Error('请重新读取机型版本')
    body.version = input.version; body.reason = text(input.reason, 500, true)
  }
  return body
}
export function productQueryBody(value: unknown): ProductQuery {
  const input = object(value)
  if (!positive(input.page) || !positive(input.page_size) || input.page_size > 100
    || (input.kind !== null && !productKinds.includes(input.kind as ProductKind))) throw Error('产品查询条件无效')
  return {query: text(input.query, 120), kind: input.kind as ProductKind | null,
    model_id: modelId(input.model_id), page: input.page, page_size: input.page_size}
}
// 新的派生来源仍走原 BOM 写接口，主进程也核对明细和来源编号。
export function productBomBody(value: unknown): Record<string, unknown> {
  const input = object(value)
  if (!positive(input.product_material_id) || typeof input.base_quantity !== 'string' || receiptLotMilli(input.base_quantity) === null
    || !Array.isArray(input.lines) || !input.lines.length || input.lines.length > 100) throw Error('BOM 产品、产量或组件数量无效')
  const ids = new Set<number>()
  const lines = input.lines.map(raw => {
    const row = object(raw)
    if (!positive(row.component_material_id) || row.component_material_id === input.product_material_id || ids.has(row.component_material_id)
      || typeof row.quantity !== 'string' || receiptLotMilli(row.quantity) === null) throw Error('BOM 组件重复、自引用或用量无效')
    ids.add(row.component_material_id)
    return {component_material_id: row.component_material_id, quantity: row.quantity}
  })
  if (input.source_bom_id !== undefined && input.source_bom_id !== null && !positive(input.source_bom_id)) throw Error('来源 BOM 编号无效')
  return {product_material_id: input.product_material_id, base_quantity: input.base_quantity,
    note: text(input.note, 200), lines, ...(input.source_bom_id === undefined ? {} : {source_bom_id: input.source_bom_id})}
}
function validateBom(value: unknown): void {
  const row = object(value)
  if (!positive(row.id) || !positive(row.version) || !positive(row.product_material_id)
    || !['draft','active','retired','cancelled'].includes(String(row.status))
    || !['product_name','product_sku','product_unit'].every(key => typeof row[key] === 'string')
    || typeof row.base_quantity !== 'string' || receiptLotMilli(row.base_quantity) === null || !Array.isArray(row.lines)) throw Error('BOM 版本资料不完整')
  row.lines.forEach(raw => {const line = object(raw)
    if (!positive(line.id) || !positive(line.component_material_id) || typeof line.quantity !== 'string'
      || receiptLotMilli(line.quantity) === null || !['sku','material_name','unit'].every(key => typeof line[key] === 'string')) throw Error('BOM 组件资料不完整')})
  if (row.source_bom_id !== undefined && row.source_bom_id !== null && !positive(row.source_bom_id)) throw Error('BOM 来源资料无效')
  if (row.source_bom !== undefined && row.source_bom !== null) {
    const source = object(row.source_bom)
    if (source.id !== row.source_bom_id || !positive(source.id) || !positive(source.version)
      || !positive(source.product_material_id) || typeof source.product_name !== 'string' || typeof source.product_sku !== 'string') throw Error('BOM 来源资料无效')
  }
}
function validateProfile(value: unknown): void {
  const row = object(value)
  if (!positive(row.id) || !positive(row.material_id) || !positive(row.version)
    || !productKinds.includes(row.kind as ProductKind) || typeof row.configuration_name !== 'string'
    || typeof row.model_name !== 'string' || typeof row.model_code !== 'string' || typeof row.created_at !== 'string') throw Error('产品资料不完整，请升级服务端后重试')
  modelId(row.model_id)
  validateMaterialResult('materialDetail', row.material)
  if (object(row.material).id !== row.material_id) throw Error('产品与物料身份不一致')
}
function validateModel(value: unknown): void {
  const row = object(value)
  if (!positive(row.id) || !positive(row.version) || !positive(row.created_by) || typeof row.created_at !== 'string') throw Error('机型资料不完整')
  productModelBody(row, false)
}
export function validateProductResult(action: string, value: unknown): void {
  if (action === 'bomDetail') { validateBom(value); return }
  if (action === 'productBoms') {
    if (!Array.isArray(value)) throw Error('产品 BOM 列表格式无效')
    value.forEach(validateBom); return
  }
  if (action === 'queryProducts') {
    const row = object(value)
    if (!Array.isArray(row.items) || !positive(row.page) || !positive(row.page_size) || row.page_size > 100
      || !Number.isSafeInteger(row.total) || Number(row.total) < 0 || row.items.length > row.page_size) throw Error('产品分页数据不完整')
    if (row.items.length > Number(row.total) || row.page > Math.max(1, Math.ceil(Number(row.total) / row.page_size))) throw Error('产品分页范围不一致')
    const ids = new Set<number>(), materialIds = new Set<number>()
    row.items.forEach(item => {validateProfile(item); const id = object(item).id as number
      if (ids.has(id) || materialIds.has(object(item).material_id as number)) throw Error('产品分页包含重复项'); ids.add(id); materialIds.add(object(item).material_id as number)})
  } else if (['productDetail', 'createProduct', 'updateProduct'].includes(action)) validateProfile(value)
  else if (action === 'productModels') {
    if (!Array.isArray(value)) throw Error('机型目录格式无效')
    const ids = new Set<number>(), codes = new Set<string>()
    value.forEach(item => {validateModel(item); const row = object(item)
      if (ids.has(row.id as number) || codes.has(row.code as string)) throw Error('机型目录包含重复项')
      ids.add(row.id as number); codes.add(row.code as string)})
  } else if (['productModelDetail', 'createProductModel', 'updateProductModel'].includes(action)) validateModel(value)
  else if (['productChanges', 'productModelChanges'].includes(action)) {
    if (!Array.isArray(value)) throw Error('产品变更记录格式无效')
    value.forEach(item => { const row = object(item)
      if (!positive(row.id) || typeof row.reason !== 'string' || typeof row.changed_by_name !== 'string'
        || typeof row.created_at !== 'string') throw Error('产品变更记录不完整')
      const validate = action === 'productChanges' ? validateProfile : validateModel
      validate(row.after); if (row.before !== null) validate(row.before)
    })
  }
}
