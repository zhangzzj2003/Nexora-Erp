import type { ContactImportPreview, ContactImportResult, ContactImportRow } from './crm-api'

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function positive(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0
}

export function validateContactImportPreview(value: unknown, rows: ContactImportRow[]): asserts value is ContactImportPreview {
  if (!record(value) || !Array.isArray(value.rows) || value.rows.length !== rows.length
    || typeof value.requires_confirmation !== 'boolean') throw new Error('联系人导入预检响应格式无效')
  let needsConfirmation = false
  for (let index = 0; index < rows.length; index++) {
    const row = value.rows[index]
    if (!record(row) || row.row !== index + 1 || row.customer_id !== rows[index].customer_id
      || row.name !== rows[index].name || typeof row.customer_name !== 'string' || !row.customer_name
      || !Array.isArray(row.existing_contact_ids) || !row.existing_contact_ids.every(positive)
      || !Array.isArray(row.batch_rows)
      || !row.batch_rows.every((item: unknown) => positive(item) && item < index + 1)
      || typeof row.requires_confirmation !== 'boolean'
      || row.requires_confirmation !== Boolean(row.existing_contact_ids.length || row.batch_rows.length)) {
      throw new Error('联系人导入预检响应格式无效')
    }
    needsConfirmation ||= row.requires_confirmation
  }
  if (value.requires_confirmation !== needsConfirmation) throw new Error('联系人导入预检响应格式无效')
}

export function validateContactImportResult(value: unknown, rows: ContactImportRow[]): asserts value is ContactImportResult {
  if (!record(value) || typeof value.batch_reference !== 'string' || !/^[a-f0-9]{16}$/.test(value.batch_reference)
    || !Array.isArray(value.created) || value.created.length !== rows.length) {
    throw new Error('联系人导入结果格式无效')
  }
  const ids = new Set<number>()
  for (let index = 0; index < rows.length; index++) {
    const created = value.created[index]
    if (!record(created) || !positive(created.id) || created.customer_id !== rows[index].customer_id
      || created.name !== rows[index].name || created.version !== 1 || ids.has(created.id)) {
      throw new Error('联系人导入结果格式无效')
    }
    ids.add(created.id)
  }
}
