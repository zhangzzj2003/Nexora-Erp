// 单位目录独立于物料；停用仅限制新的选择，历史物料继续保存原名称。
export interface MaterialUnit {
  id: number; name: string; enabled: boolean; notes: string; version: number
  created_at: string; material_count: number
}
export interface MaterialUnitInput {
  name: string; enabled: boolean; notes: string; version?: number; reason?: string
}
export interface MaterialUnitChange {
  id: number; unit_id: number; before: Omit<MaterialUnit, 'material_count'> | null
  after: Omit<MaterialUnit, 'material_count'>; reason: string; changed_by_name: string; created_at: string
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('单位资料格式无效')
  return value as Record<string, unknown>
}
function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}
export function materialUnitBody(value: unknown, editing: boolean): Record<string, unknown> {
  // IPC 只接受管理字段，并在请求边界核验版本与原因。
  const input = object(value)
  if (typeof input.name !== 'string' || !input.name.trim() || input.name.length > 20
    || typeof input.notes !== 'string' || input.notes.length > 500 || typeof input.enabled !== 'boolean') {
    throw new Error('请填写有效的单位名称、状态和备注')
  }
  const body: Record<string, unknown> = {name: input.name.trim(), notes: input.notes.trim(), enabled: input.enabled}
  if (editing) {
    if (!positive(input.version) || typeof input.reason !== 'string' || !input.reason.trim() || input.reason.length > 500) {
      throw new Error('请重新读取单位版本并填写修改原因')
    }
    body.version = input.version; body.reason = input.reason.trim()
  }
  return body
}
export function validateMaterialUnitResult(action: string, value: unknown): void {
  // 服务返回缺字段时拒绝当作空目录，避免物料草稿误用另一实例的单位。
  if (!['materialUnits', 'materialUnitDetail', 'createMaterialUnit', 'updateMaterialUnit', 'materialUnitChanges'].includes(action)) return
  if (action === 'materialUnitChanges') {
    if (!Array.isArray(value)) throw new Error('单位变更记录格式无效')
    for (const raw of value) {
      const row = object(raw)
      if (!positive(row.id) || !positive(row.unit_id) || typeof row.reason !== 'string'
        || typeof row.changed_by_name !== 'string' || typeof row.created_at !== 'string') throw new Error('单位变更记录格式无效')
      validateUnit(row.after, false)
      if (row.before !== null) validateUnit(row.before, false)
    }
    return
  }
  if (action === 'materialUnits' && !Array.isArray(value)) throw new Error('单位目录格式无效')
  const ids = new Set<number>()
  const names = new Set<string>()
  for (const raw of action === 'materialUnits' ? value as unknown[] : [value]) {
    const row = validateUnit(raw, true)
    if (ids.has(row.id) || names.has(row.name)) throw new Error('单位目录存在重复项')
    ids.add(row.id); names.add(row.name)
  }
}
function validateUnit(raw: unknown, count: boolean): MaterialUnit {
  const row = object(raw)
  if (!positive(row.id) || !positive(row.version) || typeof row.name !== 'string' || !row.name
    || typeof row.enabled !== 'boolean' || typeof row.notes !== 'string' || typeof row.created_at !== 'string'
    || (count && (typeof row.material_count !== 'number' || !Number.isSafeInteger(row.material_count) || row.material_count < 0))) {
    throw new Error('单位响应格式无效，请升级 ERP 服务')
  }
  return row as unknown as MaterialUnit
}
