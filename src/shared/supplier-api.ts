// 完善条件集中定义，物料编辑器、供应商管理与 IPC 共享同一份资料契约。
export const supplierFieldLimits = {
  contact_name: 80, phone: 40, email: 150, address: 300, tax_number: 80,
  bank_name: 120, bank_account: 80, notes: 1000
} as const
export type SupplierProfile = Record<keyof typeof supplierFieldLimits, string>
export interface Supplier extends Partial<SupplierProfile> {
  id: number
  name: string
  version: number
  profile_status?: 'pending' | 'complete'
}
export interface SupplierInput extends Partial<SupplierProfile> {
  name: string
  version?: number
  reason?: string
}
export function supplierStatusLabel(supplier: Supplier): string {
  return supplier.profile_status === 'complete' ? '已完善' : '待完善供应商'
}
export function supplierDraft(supplier?: Supplier): SupplierInput & SupplierProfile {
  // 重开窗口重新取资料，避免把上一个供应商的联系信息留在新增草稿里。
  return {
    name: supplier?.name ?? '', version: supplier?.version, reason: '',
    contact_name: supplier?.contact_name ?? '', phone: supplier?.phone ?? '',
    email: supplier?.email ?? '', address: supplier?.address ?? '',
    tax_number: supplier?.tax_number ?? '', bank_name: supplier?.bank_name ?? '',
    bank_account: supplier?.bank_account ?? '', notes: supplier?.notes ?? ''
  }
}
export function supplierBody(payload: unknown, editing: boolean): Record<string, string | number> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('供应商资料格式无效')
  const input = payload as Record<string, unknown>
  const body: Record<string, string | number> = {}
  for (const [key, limit] of Object.entries({ name: 120, ...supplierFieldLimits, reason: 500 })) {
    if (input[key] === undefined) continue
    if (typeof input[key] !== 'string' || input[key].length > limit) throw new Error('供应商字段类型或长度无效')
    body[key] = input[key].trim()
  }
  if (!body.name) throw new Error('供应商名称无效')
  if (editing) {
    if (!body.reason) throw new Error('档案名称或修改原因无效')
    if (typeof input.version !== 'number' || !Number.isSafeInteger(input.version) || input.version < 1) {
      throw new Error('供应商版本无效')
    }
    body.version = input.version
  }
  return body
}
