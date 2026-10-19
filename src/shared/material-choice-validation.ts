import { validateMaterialUses } from './material-uses.ts'
import type { MaterialChoice } from './material-api'
import { validateMaterialSpecs } from './material-category-validation.ts'
// 各业务仍按自己的权限读取选料资料；新增展示字段在主进程统一校验。
const fieldLimits: Record<string, number> = {
  sku: 40, name: 120, unit: 20, category_code: 10, category_name: 200,
  specification: 200, package: 80, brand: 120, manufacturer_part_number: 120,
  electrical_value: 80, tolerance: 80, rated_voltage: 80, rated_power: 80,
  temperature_range: 80, compliance: 120, notes: 1000
}
const operations = new Set(['crmOptions', 'afterSalesOverview', 'qualityOverview',
  'equipmentOverview', 'inventoryWarnings', 'mrpOptions'])
// 单条只读资料不要求编辑版本；历史单据可继续沿用原编码，只核验明确附带的当前资料。
export function validateMaterialChoice(value: unknown): asserts value is MaterialChoice {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('业务物料资料格式无效')
  const row = value as Record<string, unknown>
  if (typeof row.id !== 'number' || !Number.isSafeInteger(row.id) || row.id <= 0) throw new Error('业务物料编号无效')
  validateMaterialSpecs(row)
  validateMaterialUses(row)
  for (const [key, limit] of Object.entries(fieldLimits)) {
    // 旧接口只有基础四字段；提供的详情必须符合现有结构与长度约束。
    if (row[key] === undefined && !['sku', 'name', 'unit'].includes(key)) continue
    if (typeof row[key] !== 'string' || row[key].length > limit) throw new Error('业务物料字段类型或长度无效')
  }
  // 即使服务端没有同时返回规格数组，也不能把畸形摘要或模板版本送进展示层。
  if (row.spec_summary !== undefined && (typeof row.spec_summary !== 'string' || row.spec_summary.length > 40000))
    throw new Error('物料规格摘要响应无效')
  if (row.spec_template_version !== undefined && (typeof row.spec_template_version !== 'number'
    || !Number.isSafeInteger(row.spec_template_version) || row.spec_template_version <= 0)) throw new Error('物料规格模板版本无效')
}
// 单据行和资料快照是两个来源；不能用快照自身的 ID 代替原单据行的真实物料身份。
export function validateMaterialMetadata(value: unknown, materialId: unknown): asserts value is MaterialChoice {
  validateMaterialChoice(value)
  if (typeof materialId !== 'number' || !Number.isSafeInteger(materialId) || materialId <= 0 || value.id !== materialId)
    throw new Error('单据物料资料与当前行身份不一致')
}
export function validateMaterialChoiceResult(action: string, data: unknown): void {
  if (!operations.has(action)) return
  const rows = data && typeof data === 'object' && 'materials' in data ? data.materials : undefined
  if (!Array.isArray(rows)) throw new Error('业务物料响应格式无效')
  const ids = new Set<number>()
  for (const raw of rows) {
    validateMaterialChoice(raw)
    if (ids.has(raw.id)) throw new Error('业务物料编号无效或重复')
    ids.add(raw.id)
  }
}
// ReceiptLine 的读取与写回共用可选资料边界；旧服务不带 material 时不改变原单据契约。
const documentOperations = new Set([
  'otherInbounds', 'createOtherInbound', 'reopenOtherInbound', 'postOtherInbound', 'cancelOtherInbound', 'reverseOtherInbound',
  'warehouseOutbounds', 'createOtherOutbound', 'postWarehouseOutbound', 'cancelOtherOutbound', 'reverseOtherOutbound',
  'stockAdjustments', 'createStockAdjustment', 'submitStockAdjustment', 'approveStockAdjustment', 'rejectStockAdjustment',
  'cancelStockAdjustment', 'postStockAdjustment', 'reverseStockAdjustment',
  'receipts', 'createReceipt', 'postReceipt', 'reverseReceipt', 'transfers', 'createTransfer', 'postTransfer', 'reverseTransfer'
])
export function validateDocumentMaterialResult(action: string, data: unknown): void {
  if (!documentOperations.has(action)) return
  for (const raw of Array.isArray(data) ? data : [data]) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('单据物料响应格式无效')
    const row = raw as Record<string, unknown>
    if (row.lines === undefined) continue
    if (!Array.isArray(row.lines)) throw new Error('单据物料明细格式无效')
    for (const entry of row.lines) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('单据物料明细格式无效')
      const line = entry as Record<string, unknown>
      if (line.material !== undefined) validateMaterialMetadata(line.material, line.material_id)
    }
  }
}
