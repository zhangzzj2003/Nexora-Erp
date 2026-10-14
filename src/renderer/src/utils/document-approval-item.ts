import type { DocumentApprovalTarget, DocumentApprovalType } from '../../../shared/document-approval-api'

// 不同业务表的 ID 会重复；页脚必须同时匹配单据类型，不能把另一类详情绑定到同号单据。
export function findDocumentApprovalItem<T extends { id: number }>(
  target: DocumentApprovalTarget | null | undefined,
  type: DocumentApprovalType,
  items: readonly T[]
): T | null {
  if (target?.document_type !== type) return null
  return items.find(item => item.id === target.document_id) ?? null
}
