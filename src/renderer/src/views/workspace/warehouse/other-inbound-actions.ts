import type { OtherInbound } from '../../../../../shared/erp-api'

export type OtherInboundAction = 'approval' | 'post' | 'lots' | 'cancel' | 'reversalApproval' | 'reverse' | 'reopen'
export interface OtherInboundPermissions { create: boolean; post: boolean; cancel: boolean; reverse: boolean }
interface InboundActionItem { key: OtherInboundAction; label: string; variant: 'primary' | 'secondary' }

// 列表与详情共用可用操作规则，避免两处按钮随审批或仓库状态变化后产生差异。
export function otherInboundActions(inbound: OtherInbound, permissions: OtherInboundPermissions): InboundActionItem[] {
  const actions: InboundActionItem[] = [{ key: 'approval', label: '审批记录 / 送审', variant: 'secondary' }]
  if (inbound.status === 'draft') {
    if (inbound.approval?.status === 'approved' && permissions.post) {
      actions.push({ key: 'post', label: '确认入库', variant: 'primary' },
        { key: 'lots', label: '登记实物批次（可选）', variant: 'primary' })
    }
    if (!['submitted', 'approved'].includes(inbound.approval?.status ?? '') && permissions.cancel) {
      actions.push({ key: 'cancel', label: '取消', variant: 'secondary' })
    }
  }
  // 已取消单据只能另建新单，不能恢复原单或沿用原审批。
  if (inbound.status === 'cancelled' && permissions.create) {
    actions.push({ key: 'reopen', label: '重开为新单', variant: 'primary' })
  }
  // 已冲销单据不再显示重复执行按钮。
  if (inbound.status === 'posted' && !inbound.reversal_id) {
    actions.push({ key: 'reversalApproval', label: '冲销审批', variant: 'secondary' })
    if (inbound.reversal_approval?.status === 'approved' && permissions.reverse) {
      actions.push({ key: 'reverse', label: '执行冲销', variant: 'secondary' })
    }
  }
  return actions
}
