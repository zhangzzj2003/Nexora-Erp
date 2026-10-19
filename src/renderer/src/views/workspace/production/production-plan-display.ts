import type { ProductionPlan, ProductionPlanDetail, ProductionPlanLine } from '../../../../../shared/production-plan-api'

export const planPriority = { normal: '普通', high: '优先', urgent: '紧急' }
export const planProgress = { unreleased: '待下达', released: '已下达', in_progress: '生产中', completed: '报工完成' }
export function planStatus(plan: ProductionPlan): string {
  if (plan.status === 'cancelled') return '已取消'
  return { draft: '草稿', submitted: '待审批', approved: '已批准', rejected: '已驳回', withdrawn: '已撤回', executed: '已批准' }[plan.approval.status] ?? '待核对'
}
export function canReleasePlan(plan: ProductionPlanDetail, line: ProductionPlanLine, permissions: readonly string[]): boolean {
  // 只有当前固定批准与本计划的剩余行可以下达；工单建单权限仍需独立拥有。
  return plan.status !== 'cancelled' && ['approved', 'executed'].includes(plan.approval.status)
    && line.plan_id === plan.id && Number(line.unreleased_quantity) > 0
    && permissions.includes('production_plan.release') && permissions.includes('work_order.create')
}
export function canCancelPlan(plan: ProductionPlanDetail, permissions: readonly string[]): boolean {
  return permissions.includes('production_plan.cancel') && plan.status !== 'cancelled'
    && !['approved', 'submitted'].includes(plan.approval.status)
}
