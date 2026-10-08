import type { DocumentApprovalRecord } from '../../../shared/document-approval-api'

type ApprovalSummary = DocumentApprovalRecord['summary']

// 其他入库的服务端摘要先返回四个单据头字段，其余行是固定送审物料。
// 只划分展示位置，原始标签、数量和单位完整保留，不能用当前列表覆盖审批快照。
const inboundHeaderLabels = new Set(['仓库', '用途', '入库说明', '参考号'])
export function documentApprovalLayout(record: DocumentApprovalRecord | null): {
  basic: ApprovalSummary
  lines: ApprovalSummary
  showLines: boolean
} {
  if (!record) return { basic: [], lines: [], showLines: false }
  if (record.document_type !== 'WarehouseInbound') {
    // 其他领域摘要包含金额、附件和历史依据，继续完整展示，不猜测字段含义。
    return { basic: record.summary, lines: [], showLines: false }
  }
  return {
    basic: record.summary.filter(item => inboundHeaderLabels.has(item.label)),
    lines: record.summary.filter(item => !inboundHeaderLabels.has(item.label)),
    showLines: true
  }
}
