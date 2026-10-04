import type { CrmQuoteAttachment } from './crm-api'

const mediaByExtension: Record<string, CrmQuoteAttachment['media_type']> = {
  pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('报价附件响应格式无效')
  return value as Record<string, unknown>
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function validText(value: unknown, max: number): value is string {
  return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f]/.test(value)
}

function validateItem(value: unknown, quoteId: number): CrmQuoteAttachment {
  const row = object(value)
  const extension = typeof row.file_name === 'string' ? row.file_name.toLowerCase().split('.').at(-1) ?? '' : ''
  if (!positive(row.id) || row.quote_id !== quoteId || !validText(row.file_name, 120)
    || !mediaByExtension[extension] || row.media_type !== mediaByExtension[extension]
    || !positive(row.byte_count) || row.byte_count > 5 * 1024 * 1024
    || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256)
    || !validText(row.reason, 200) || !positive(row.created_by)
    || !validText(row.created_by_name, 120) || !validText(row.created_at, 40)) {
    throw new Error('报价附件响应格式无效')
  }
  if (row.reversal !== null) {
    const reversal = object(row.reversal)
    if (!positive(reversal.id) || !validText(reversal.reason, 200) || !positive(reversal.created_by)
      || !validText(reversal.created_by_name, 120) || !validText(reversal.created_at, 40)) {
      throw new Error('报价附件撤销响应格式无效')
    }
  }
  return row as unknown as CrmQuoteAttachment
}

export function validateCrmQuoteAttachmentResult(action: string, result: unknown, quoteId: number): void {
  if (action === 'crmQuoteAttachments') {
    const page = object(result)
    if (page.quote_id !== quoteId || typeof page.can_modify !== 'boolean'
      || !Array.isArray(page.items)) throw new Error('报价附件列表响应格式无效')
    const ids = new Set<number>()
    for (const value of page.items) {
      const item = validateItem(value, quoteId)
      if (ids.has(item.id)) throw new Error('报价附件列表响应格式无效')
      ids.add(item.id)
    }
    return
  }
  if (action === 'addCrmQuoteAttachment' || action === 'reverseCrmQuoteAttachment') {
    validateItem(result, quoteId)
    if (action === 'reverseCrmQuoteAttachment' && !(result as CrmQuoteAttachment).reversal) {
      throw new Error('报价附件撤销响应格式无效')
    }
  }
}
