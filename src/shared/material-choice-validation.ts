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
export function validateMaterialChoiceResult(action: string, data: unknown): void {
  if (!operations.has(action)) return
  const rows = data && typeof data === 'object' && 'materials' in data ? data.materials : undefined
  if (!Array.isArray(rows)) throw new Error('业务物料响应格式无效')
  const ids = new Set<number>()
  for (const raw of rows) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('业务物料资料格式无效')
    const row = raw as Record<string, unknown>
    validateMaterialSpecs(row)
    if (typeof row.id !== 'number' || !Number.isSafeInteger(row.id) || row.id <= 0 || ids.has(row.id)) {
      throw new Error('业务物料编号无效或重复')
    }
    ids.add(row.id)
    for (const [key, limit] of Object.entries(fieldLimits)) {
      // 旧服务端只提供四个基础字段；详情若提供，必须为受长度限制的字符串。
      if (row[key] === undefined && !['sku', 'name', 'unit'].includes(key)) continue
      if (typeof row[key] !== 'string' || row[key].length > limit) throw new Error('业务物料字段类型或长度无效')
    }
  }
}
