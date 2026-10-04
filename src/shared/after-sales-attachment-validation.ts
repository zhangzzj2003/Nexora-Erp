import type { AfterSalesAttachment } from './after-sales-api'

const mediaByExtension: Record<string, AfterSalesAttachment['media_type']> = {
  pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('售后附件响应格式无效')
  return value as Record<string, unknown>
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function validText(value: unknown, max: number): value is string {
  return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f]/.test(value)
}

function validateItem(value: unknown, caseId: number): AfterSalesAttachment {
  const row = object(value)
  const extension = typeof row.file_name === 'string' ? row.file_name.toLowerCase().split('.').at(-1) ?? '' : ''
  if (!positive(row.id) || row.case_id !== caseId || !validText(row.file_name, 120)
    || !mediaByExtension[extension] || row.media_type !== mediaByExtension[extension]
    || !positive(row.byte_count) || row.byte_count > 5 * 1024 * 1024
    || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256)
    || !validText(row.reason, 200) || !positive(row.created_by)
    || !validText(row.created_by_name, 120) || !validText(row.created_at, 40)) {
    throw new Error('售后附件响应格式无效')
  }
  if (row.reversal !== null) {
    const reversal = object(row.reversal)
    if (!positive(reversal.id) || !validText(reversal.reason, 200) || !positive(reversal.created_by)
      || !validText(reversal.created_by_name, 120) || !validText(reversal.created_at, 40)) {
      throw new Error('售后附件撤销响应格式无效')
    }
  }
  return row as unknown as AfterSalesAttachment
}

export function validateAfterSalesAttachmentResult(action: string, result: unknown, caseId: number): void {
  if (action === 'afterSalesAttachments') {
    const page = object(result)
    if (page.case_id !== caseId || typeof page.can_modify !== 'boolean'
      || !Array.isArray(page.items)) throw new Error('售后附件列表响应格式无效')
    const ids = new Set<number>()
    for (const value of page.items) {
      const item = validateItem(value, caseId)
      if (ids.has(item.id)) throw new Error('售后附件列表响应格式无效')
      ids.add(item.id)
    }
    return
  }
  if (action === 'addAfterSalesAttachment' || action === 'reverseAfterSalesAttachment') {
    validateItem(result, caseId)
    if (action === 'reverseAfterSalesAttachment' && !(result as AfterSalesAttachment).reversal) {
      throw new Error('售后附件撤销响应格式无效')
    }
  }
}
