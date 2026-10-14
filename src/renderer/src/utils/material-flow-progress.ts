import type { MaterialFlowDocument } from '../../../shared/material-flow-api'

// 执行记录统一展示业务名称，包含不产生物料明细的编辑、补发建单及关闭事件。
export const materialFlowExecutionLabels: Record<string, string> = {
  dispatch: '实际发料', sign: '生产签收', receive: '接收', execute: '分批执行',
  collect: '旧料交接', old_receive: '旧料交接', handover_return: '交接退回',
  edit: '修改草稿', create_dispatch: '生成补发单', close: '关闭余额', reverse: '审批更正 / 冲销'
}

// 审批记录在首批执行后已记为 executed，但业务余额及签收仍继续独立累计。
export function materialFlowExecutionHint(document: Pick<MaterialFlowDocument, 'kind' | 'status' | 'lines'>): string {
  if (document.kind === 'receipt') return ''
  if (document.status === 'reversed') return '本单已按批准依据追加冲销记录，原执行历史仍保留。'
  if (document.status === 'closed') return '未执行余额已关闭；已发生的发出、签收或接收记录仍然保留。'
  const remaining = document.lines.filter(line => Number(line.remaining_quantity) > 0)
    .map(line => `${line.sku} ${line.remaining_quantity} ${line.unit}`).join('；')
  if (document.kind === 'dispatch') return document.status === 'completed'
    ? '本单批准数量已发完；发出完成不代表生产已签收，请在关联领料单核对实收和交接差额。'
    : document.status === 'partial'
      ? `审批已完成，本单已分批发出，仍待发：${remaining}。生产签收进度另行记录，发出与签收均不抹平差额。`
      : '审批已完成，请按实际实物分批发料；出库时扣减库存，生产另行确认实收。'
  if (document.kind === 'exchange') return document.status === 'completed'
    ? '旧料交接与等量补发均已完成，补发材料已由生产签收。'
    : '审批已完成，旧料交接、新料发出与生产签收分别记录；补发材料全部签收后才完成换料。'
  return document.status === 'completed'
    ? '本单退料已全部接收，实际入库数量和来源成本已按各批记录。'
    : document.status === 'partial'
      ? `审批已完成，退料已分批接收，仍待收：${remaining}。尚未接收的数量不会提前增加库存。`
      : '审批已完成，请核对实物后分批接收；每次按实际良品接收量增加库存。'
}
