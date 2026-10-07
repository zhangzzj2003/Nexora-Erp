import type { JournalAttachment } from './erp-api'

const mediaByExtension: Record<string, JournalAttachment['media_type']> = {
  pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('凭证附件响应格式无效')
  return value as Record<string, unknown>
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function text(value: unknown, max: number): value is string {
  return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f]/.test(value)
}

function validateItem(value: unknown, journalId: number): JournalAttachment {
  const row = object(value)
  const extension = typeof row.file_name === 'string' ? row.file_name.toLowerCase().split('.').at(-1) ?? '' : ''
  if (!positive(row.id) || row.journal_id !== journalId || !text(row.file_name, 120)
    || !mediaByExtension[extension] || row.media_type !== mediaByExtension[extension]
    || !positive(row.byte_count) || row.byte_count > 5 * 1024 * 1024
    || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256)
    || !text(row.reason, 200) || !positive(row.created_by)
    || !text(row.created_by_name, 120) || !text(row.created_at, 40)) {
    throw new Error('凭证附件响应格式无效')
  }
  if (row.can_reverse !== undefined && typeof row.can_reverse !== 'boolean') throw new Error('凭证附件响应格式无效')
  if (row.reversal !== null) {
    const reversal = object(row.reversal)
    if (!positive(reversal.id) || !text(reversal.reason, 200) || !positive(reversal.created_by)
      || !text(reversal.created_by_name, 120) || !text(reversal.created_at, 40)) {
      throw new Error('凭证附件撤销响应格式无效')
    }
  }
  return row as unknown as JournalAttachment
}

export function validateJournalAttachmentResult(action: string, result: unknown, journalId: number): void {
  if (action === 'journalAttachments') {
    const page = object(result)
    if (page.journal_id !== journalId || typeof page.can_modify !== 'boolean'
      || !Array.isArray(page.items)) throw new Error('凭证附件列表响应格式无效')
    const ids = new Set<number>()
    for (const value of page.items) {
      const item = validateItem(value, journalId)
      if (ids.has(item.id)) throw new Error('凭证附件列表响应格式无效')
      ids.add(item.id)
    }
    return
  }
  if (action === 'addJournalAttachment' || action === 'reverseJournalAttachment') {
    validateItem(result, journalId)
    if (action === 'reverseJournalAttachment' && !(result as JournalAttachment).reversal) {
      throw new Error('凭证附件撤销响应格式无效')
    }
  }
}
