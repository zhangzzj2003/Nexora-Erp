import type { DocumentApprovalRecord } from './document-approval-api'
import { validateDocumentApprovalRecord } from './document-approval-api.ts'

// 由服务端沿真实库存流水定位原单，客户端不能把冲销记录 ID 当成业务主单 ID。
export interface InventoryLedgerDocument {
  movement_id: number
  document: DocumentApprovalRecord
}

export function validateInventoryLedgerDocument(value: unknown, movementId: number): asserts value is InventoryLedgerDocument {
  if (!value || typeof value !== 'object' || !('movement_id' in value)
      || value.movement_id !== movementId || !('document' in value)) {
    throw Error('单据详情与当前库存流水不一致，请重新读取。')
  }
  validateDocumentApprovalRecord(value.document)
}
