import { materialSpecBody, validateMaterialSpecs } from './material-category-validation.ts'
// 输入和响应都在主进程边界核验；资料为空与响应漏字段不能混为一谈。
const lengths: Record<string, number> = {
  sku: 40, name: 120, unit: 20, category_code: 10, specification: 200,
  package: 80, brand: 120, manufacturer_part_number: 120, electrical_value: 80,
  tolerance: 80, rated_voltage: 80, rated_power: 80, temperature_range: 80,
  compliance: 120, notes: 1000, reason: 500
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('物料资料格式无效')
  return value as Record<string, unknown>
}
function positiveVersion(value: unknown): boolean {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}
export function materialBody(payload: unknown, editing: boolean): Record<string, unknown> {
  const input = object(payload)
  const body: Record<string, unknown> = {}
  for (const [key, limit] of Object.entries(lengths)) {
    if (input[key] !== undefined) {
      if (typeof input[key] !== 'string' || input[key].length > limit) throw new Error('物料字段类型或长度无效')
      body[key] = input[key].trim()
    }
  }
  if (!body.name || !body.unit) throw new Error('请填写物料名称和单位')
  if (input.unit_id !== undefined) {
    if (!positiveVersion(input.unit_id)) throw new Error('所选单位编号无效')
    body.unit_id = input.unit_id
  }
  if (input.suppliers !== undefined) {
    // 绑定只能传已有编号或新名称，禁止通过物料接口伪造供应商完善状态。
    if (!Array.isArray(input.suppliers) || input.suppliers.length > 20) throw new Error('供应商绑定数量无效')
    body.suppliers = input.suppliers.map(raw => {
      const choice = object(raw)
      if (Object.keys(choice).some(key => !['supplier_id', 'name'].includes(key))) throw new Error('供应商绑定格式无效')
      if (choice.supplier_id !== undefined && choice.name === undefined && positiveVersion(choice.supplier_id)) {
        return { supplier_id: choice.supplier_id }
      }
      if (choice.supplier_id === undefined && typeof choice.name === 'string' && choice.name.trim()
        && choice.name.length <= 120) return { name: choice.name.trim() }
      throw new Error('供应商绑定格式无效')
    })
  }
  if (editing) {
    if (!positiveVersion(input.version)) throw new Error('物料版本无效，请重新加载')
    body.version = input.version
  }
  return {...body, ...materialSpecBody(input)}
}
export function validateMaterialResult(action: string, data: unknown): void {
  if (action === 'materialCategories') {
    if (!Array.isArray(data)) throw new Error('物料分类响应格式无效')
    const codes = new Set<string>()
    for (const raw of data) {
      const group = object(raw)
      if (typeof group.code !== 'string' || !/^[A-Z]{2,4}$/.test(group.code)
        || typeof group.name !== 'string' || !group.name || !Array.isArray(group.children)) {
        throw new Error('物料分类响应格式无效')
      }
      for (const rawChild of group.children) {
        const child = object(rawChild)
        if (typeof child.code !== 'string' || !new RegExp(`^${group.code}-[A-Z]{2,4}$`).test(child.code)
          || codes.has(child.code) || typeof child.name !== 'string' || !child.name) {
          throw new Error('物料分类响应格式无效')
        }
        codes.add(child.code)
      }
    }
    return
  }
  if (!['materials', 'materialDetail', 'createMaterial', 'updateMaterial'].includes(action)) return
  if (action === 'materials' && !Array.isArray(data)) throw new Error('物料响应格式无效')
  for (const raw of action === 'materials' ? data as unknown[] : [data]) {
    const row = object(raw)
    validateMaterialSpecs(row)
    if (!positiveVersion(row.id) || !positiveVersion(row.version)) throw new Error('物料响应版本或编号无效，请升级服务端')
    // 中文分类仅用于展示，不加入可写字段白名单；旧列表没有此字段时仍兼容。
    if (row.category_name !== undefined && (typeof row.category_name !== 'string' || row.category_name.length > 200)) {
      throw new Error('物料分类名称响应无效')
    }
    if (row.supplier_ids !== undefined && (!Array.isArray(row.supplier_ids)
      || row.supplier_ids.some(value => !positiveVersion(value))
      || new Set(row.supplier_ids).size !== row.supplier_ids.length)) throw new Error('物料供应商绑定响应无效')
    for (const [key, limit] of Object.entries(lengths)) {
      if (key === 'reason') continue
      if (typeof row[key] !== 'string' || row[key].length > limit) throw new Error('物料响应字段无效，请升级服务端')
    }
  }
}
