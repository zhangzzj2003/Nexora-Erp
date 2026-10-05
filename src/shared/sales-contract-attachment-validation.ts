import type { SalesOrderContractAttachment } from './erp-api'

const mediaByExtension: Record<string, SalesOrderContractAttachment['media_type']> = {
  pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg'
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('合同附件响应格式无效')
  return value as Record<string, unknown>
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function validText(value: unknown, max: number): value is string {
  return typeof value === 'string' && !!value.trim() && value.length <= max && !/[\x00-\x1f]/.test(value)
}

function validateItem(value: unknown, revisionId: number): SalesOrderContractAttachment {
  const row = object(value)
  const extension = typeof row.file_name === 'string' ? row.file_name.toLowerCase().split('.').at(-1) ?? '' : ''
  if (!positive(row.id) || row.revision_id !== revisionId || !validText(row.file_name, 120)
    || !mediaByExtension[extension] || row.media_type !== mediaByExtension[extension]
    || !positive(row.byte_count) || row.byte_count > 5 * 1024 * 1024
    || typeof row.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(row.sha256)
    || !validText(row.reason, 200) || !positive(row.created_by)
    || !validText(row.created_by_name, 120) || !validText(row.created_at, 40)) {
    throw new Error('合同附件响应格式无效')
  }
  if (row.reversal !== null) {
    const reversal = object(row.reversal)
    if (!positive(reversal.id) || !validText(reversal.reason, 200) || !positive(reversal.created_by)
      || !validText(reversal.created_by_name, 120) || !validText(reversal.created_at, 40)) {
      throw new Error('合同附件撤销响应格式无效')
    }
  }
  return row as unknown as SalesOrderContractAttachment
}

export function validateSalesContractAttachmentResult(action: string, result: unknown,
  orderId: number, revisionId: number): void {
  if (action === 'salesContractAttachments') {
    const page = object(result)
    if (page.order_id !== orderId || page.revision_id !== revisionId
      || typeof page.can_modify !== 'boolean' || !Array.isArray(page.items)) {
      throw new Error('合同附件列表响应格式无效')
    }
    const ids = new Set<number>()
    for (const value of page.items) {
      const item = validateItem(value, revisionId)
      if (ids.has(item.id)) throw new Error('合同附件列表响应格式无效')
      ids.add(item.id)
    }
    return
  }
  if (action === 'addSalesContractAttachment' || action === 'reverseSalesContractAttachment') {
    validateItem(result, revisionId)
    if (action === 'reverseSalesContractAttachment' && !(result as SalesOrderContractAttachment).reversal) {
      throw new Error('合同附件撤销响应格式无效')
    }
  }
}
