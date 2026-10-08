import type { DocumentApprovalEvent, DocumentApprovalRecord } from '../../../shared/document-approval-api'

export type ApprovalNodeState = 'completed' | 'current' | 'pending' | 'rejected' | 'withdrawn'
export interface ApprovalProgressNode {
  key: string
  name: string
  state: ApprovalNodeState
  caption: string
  role: string | null
  event?: DocumentApprovalEvent
}

const statusLabels = {
  draft: '未送审', submitted: '审批中', approved: '已批准，待执行',
  rejected: '已驳回', withdrawn: '已撤回', executed: '已执行'
} as const

export function documentApprovalProgress(record: DocumentApprovalRecord) {
  // 旧业务事实没有统一审批实例，不能给它画出虚假的送审或批准节点。
  const historical = record.intent === 'execute' && record.version === 0 &&
    ['posted', 'cancelled', 'confirmed', 'partially_shipped', 'shipped', 'closed', 'released',
      'in_progress', 'completed', 'converted', 'processing', 'received', 'repaired', 'reversed',
      'accepted', 'reported'].includes(record.business_status)
  const convertedRequest = record.document_type === 'PurchaseRequest' && record.version === 0 &&
    record.business_status === 'approved' && !record.can_submit
  const historyNote = historical ? '已处理单据保留原业务记录，不补造审批记录。'
    : convertedRequest ? '申请已无待转数量，保留原转单记录，不补造审批。' : ''
  if (historyNote) return { label: '历史业务记录', summary: historyNote, completed: 0, nodes: [] as ApprovalProgressNode[] }

  // 只从本次送审事件取人员；重新送审后不能把上一轮审核人算作已完成。
  const events = record.events.filter(event => event.generation === record.generation)
  const eventFor = (action: DocumentApprovalEvent['action'], step?: number) =>
    events.find(event => event.action === action && (step === undefined || event.step === step))
  const interrupted = record.status === 'rejected' || record.status === 'withdrawn'
  const nodes: ApprovalProgressNode[] = [{
    key: 'submit', name: '送审', state: record.status === 'draft' ? 'current' : 'completed',
    caption: record.status === 'draft' ? '待送审' : '已送审', role: null, event: eventFor('submit')
  }]
  record.steps.forEach((step, index) => {
    let state: ApprovalNodeState = index < record.current_step ? 'completed' : 'pending'
    if (index === record.current_step && record.status === 'submitted') state = 'current'
    if (index === record.current_step && interrupted) state = record.status === 'rejected' ? 'rejected' : 'withdrawn'
    nodes.push({ key: `step-${index}`, name: step.name, state, role: step.role,
      caption: state === 'completed' ? '已完成' : state === 'current' ? '待处理'
        : state === 'rejected' ? '已驳回' : state === 'withdrawn' ? '已撤回' : interrupted ? '已中止' : '待审批',
      event: eventFor(state === 'rejected' ? 'reject' : state === 'withdrawn' ? 'withdraw' : 'approve', index) })
  })
  // 未送审时服务端尚无固定步骤，使用明确的占位说明，不猜测当前审批模板。
  if (!record.steps.length) nodes.push({ key: 'approval', name: '审批', state: 'pending', caption: '送审后确定步骤', role: null })
  nodes.push({ key: 'execute', name: '业务执行', role: null,
    state: record.status === 'executed' ? 'completed' : record.status === 'approved' ? 'current'
      : record.status === 'withdrawn' && record.current_step === record.steps.length ? 'withdrawn' : 'pending',
    caption: record.status === 'executed' ? '已执行' : record.status === 'approved' ? '待执行'
      : interrupted ? '已中止' : '批准后执行', event: eventFor('execute') })
  const summary = record.status === 'submitted' ? `当前待办：${record.steps[record.current_step]?.name ?? '审批'}`
    : record.status === 'approved' ? '审批已完成，请在业务页面执行对应操作。'
      : record.status === 'executed' ? '审批与业务执行均已完成。'
        : interrupted ? '本次审批已中止，重新送审后重新审批。' : '提交后进入审批流程。'
  return { label: statusLabels[record.status], summary, completed: record.current_step, nodes }
}
