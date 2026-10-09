import type { OtherInbound } from '../../../../../shared/erp-api'

export type OtherInboundAction = 'approval' | 'post' | 'lots' | 'cancel' | 'reversalApproval' | 'reverse' | 'reopen'
export interface OtherInboundPermissions { create: boolean; post: boolean; cancel: boolean; reverse: boolean }
interface InboundActionItem { key: OtherInboundAction; label: string; variant: 'primary' | 'secondary' }

// 列表与详情共用可用操作规则，避免两处按钮随审批或仓库状态变化后产生差异。
export function otherInboundActions(inbound: OtherInbound, permissions: OtherInboundPermissions): InboundActionItem[] {
  const actions: InboundActionItem[] = [{ key: 'approval', label: '审批记录 / 送审', variant: 'secondary' }]
  if (inbound.status === 'draft' || inbound.status === 'partially_posted' && !inbound.reversal_id) {
    if (inbound.approval?.status === 'approved' && permissions.post) {
      actions.push({ key: 'post', label: inbound.status === 'partially_posted' ? '确认剩余入库' : '确认入库', variant: 'primary' },
        { key: 'lots', label: inbound.status === 'partially_posted' ? '继续分批入库' : '登记实物批次（可选）', variant: 'primary' })
    }
    if (inbound.status === 'draft' && !['submitted', 'approved'].includes(inbound.approval?.status ?? '') && permissions.cancel) {
      actions.push({ key: 'cancel', label: '取消', variant: 'secondary' })
    }
  }
  // 两类终态共用一次重开额度，成功保存后的原单不再提供重开入口。
  if ((inbound.status === 'cancelled' || inbound.reversal_id) && !inbound.reopened_as_id && permissions.create) {
    actions.push({ key: 'reopen', label: inbound.reversal_id ? '冲销重开新单' : '重开为新单', variant: 'primary' })
  }
  // 已冲销单据不再显示重复执行按钮。
  if (['posted', 'partially_posted'].includes(inbound.status) && !inbound.reversal_id) {
    actions.push({ key: 'reversalApproval', label: '冲销审批', variant: 'secondary' })
    if (inbound.reversal_approval?.status === 'approved' && permissions.reverse) {
      actions.push({ key: 'reverse', label: '执行冲销', variant: 'secondary' })
    }
  }
  return actions
}

// 表格优先排列常用动作；次要动作按列宽展开或进入菜单，取消与冲销不作为默认主操作。
export function otherInboundRowActions(inbound: OtherInbound, permissions: OtherInboundPermissions) {
  const actions = otherInboundActions(inbound, permissions)
  const primary = actions.find(item => item.key === 'post')
    ?? actions.find(item => item.key === 'reopen') ?? actions[0]!
  return {
    primary: { ...primary, label: primary.key === 'approval'
      ? (inbound.status === 'draft' ? '审批 / 送审' : '审批记录') : primary.label },
    more: actions.filter(item => item.key !== primary.key)
  }
}
