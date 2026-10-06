import type { MaterialSupplierInput } from '../../../shared/material-api'
import type { Supplier } from '../../../shared/supplier-api'
import { supplierStatusLabel } from '../../../shared/supplier-api.ts'

// 编号和新名称使用不同前缀，数字名称也不会被误认为供应商编号。
export function supplierOption(supplier: Supplier): { value: string; label: string } {
  return { value: `id:${supplier.id}`, label: `${supplier.name} · ${supplierStatusLabel(supplier)}` }
}
export function newSupplierOption(name: string, suppliers: readonly Supplier[]): { value: string; label: string; disabled?: boolean } {
  const trimmed = name.trim()
  const matches = suppliers.filter(item => item.name.toLowerCase() === trimmed.toLowerCase())
  const existing = matches.find(item => item.name === trimmed) ?? (matches.length === 1 ? matches[0] : undefined)
  if (existing) return supplierOption(existing)
  return {
    value: `new:${trimmed}`, label: `新建“${trimmed}”（待完善供应商）`,
    disabled: !trimmed || trimmed.length > 120 || matches.length > 1
  }
}
export function supplierSelectionInput(values: readonly string[]): MaterialSupplierInput[] {
  if (values.length > 20) throw new Error('每个物料最多选择 20 家供应商')
  const unique = [...new Set(values)]
  return unique.map(value => {
    if (/^id:[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value.slice(3)))) {
      return { supplier_id: Number(value.slice(3)) }
    }
    if (value.startsWith('new:') && value.slice(4).trim() && value.slice(4).length <= 120) {
      return { name: value.slice(4).trim() }
    }
    throw new Error('供应商选择无效，请重新选择')
  })
}
