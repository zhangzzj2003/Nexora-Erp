import type { OpportunityImportPreview, OpportunityImportResult, OpportunityImportRow } from './crm-api'

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function positive(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0
}

export function validateOpportunityImportPreview(value: unknown, rows: OpportunityImportRow[]): asserts value is OpportunityImportPreview {
  if (!record(value) || !Array.isArray(value.rows) || value.rows.length !== rows.length
    || typeof value.requires_confirmation !== 'boolean') throw new Error('商机导入预检响应格式无效')
  let needsConfirmation = false
  for (let index = 0; index < rows.length; index++) {
    const row = value.rows[index]
    if (!record(row) || row.row !== index + 1 || row.customer_id !== rows[index].customer_id
      || row.title !== rows[index].title || row.owner_id !== rows[index].owner_id
      || typeof row.customer_name !== 'string' || !row.customer_name
      || typeof row.owner_name !== 'string' || !row.owner_name
      || typeof row.contact_name !== 'string'
      || !Array.isArray(row.existing_opportunity_ids) || !row.existing_opportunity_ids.every(positive)
      || !Array.isArray(row.batch_rows)
      || !row.batch_rows.every((item: unknown) => positive(item) && item < index + 1)
      || typeof row.requires_confirmation !== 'boolean'
      || row.requires_confirmation !== Boolean(row.existing_opportunity_ids.length || row.batch_rows.length)) {
      throw new Error('商机导入预检响应格式无效')
    }
    needsConfirmation ||= row.requires_confirmation
  }
  if (value.requires_confirmation !== needsConfirmation) throw new Error('商机导入预检响应格式无效')
}

export function validateOpportunityImportResult(value: unknown, rows: OpportunityImportRow[]): asserts value is OpportunityImportResult {
  if (!record(value) || typeof value.batch_reference !== 'string' || !/^[a-f0-9]{16}$/.test(value.batch_reference)
    || !Array.isArray(value.created) || value.created.length !== rows.length) {
    throw new Error('商机导入结果格式无效')
  }
  const ids = new Set<number>()
  for (let index = 0; index < rows.length; index++) {
    const created = value.created[index]
    if (!record(created) || !positive(created.id) || created.customer_id !== rows[index].customer_id
      || created.title !== rows[index].title || created.version !== 1 || ids.has(created.id)) {
      throw new Error('商机导入结果格式无效')
    }
    ids.add(created.id)
  }
}
