import type { CustomerImportPreview, CustomerImportResult } from './erp-api'

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function candidate(value: unknown): boolean {
  return record(value) && Number.isSafeInteger(value.id) && Number(value.id) > 0
    && typeof value.name === 'string' && value.name.length > 0 && value.name.length <= 120
    && (value.match === 'same_name' || value.match === 'similar_name')
}

export function validateCustomerImportPreview(value: unknown, names: string[]): asserts value is CustomerImportPreview {
  if (!record(value) || !Array.isArray(value.rows) || value.rows.length !== names.length
    || typeof value.can_import !== 'boolean' || typeof value.requires_confirmation !== 'boolean') {
    throw new Error('客户导入预检响应格式无效')
  }
  for (let index = 0; index < names.length; index++) {
    const row = value.rows[index]
    if (!record(row) || row.row !== index + 1 || row.name !== names[index]
      || !Array.isArray(row.candidates) || row.candidates.length > 10
      || !row.candidates.every(candidate) || !Array.isArray(row.batch_candidates)
      || !row.batch_candidates.every((item: unknown) => Number.isSafeInteger(item) && Number(item) > 0 && Number(item) < index + 1)
      || typeof row.can_import !== 'boolean' || typeof row.requires_confirmation !== 'boolean') {
      throw new Error('客户导入预检响应格式无效')
    }
  }
}

export function validateCustomerImportResult(value: unknown, names: string[]): asserts value is CustomerImportResult {
  if (!record(value) || typeof value.batch_reference !== 'string'
    || !/^[a-f0-9]{16}$/.test(value.batch_reference)
    || !Array.isArray(value.created) || value.created.length !== names.length) {
    throw new Error('客户导入结果格式无效')
  }
  const ids = new Set<number>()
  for (let index = 0; index < names.length; index++) {
    const row = value.created[index]
    if (!record(row) || !Number.isSafeInteger(row.id) || Number(row.id) <= 0
      || row.name !== names[index] || !Number.isSafeInteger(row.owner_id)
      || Number(row.owner_id) <= 0 || row.version !== 1 || ids.has(Number(row.id))) {
      throw new Error('客户导入结果格式无效')
    }
    ids.add(Number(row.id))
  }
}
