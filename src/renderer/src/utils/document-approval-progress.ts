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
    // 分批入库会追加多次执行，节点摘要取最近一次；下方历史仍按原顺序展示全部事件。
    (action === 'execute' ? [...events].reverse() : events).find(event => event.action === action && (step === undefined || event.step === step))
  // 部分入库已有实际执行事件，审批批准仍覆盖后续剩余额度。
  const partialInbound = record.document_type === 'WarehouseInbound' && record.business_status === 'partially_posted' && record.intent === 'execute'
  const inboundClosed = record.document_type === 'WarehouseInbound' && record.business_status === 'reversed' && record.intent === 'execute'
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
    state: record.status === 'executed' ? 'completed' : inboundClosed ? 'withdrawn' : record.status === 'approved' ? 'current'
      : record.status === 'withdrawn' && record.current_step === record.steps.length ? 'withdrawn' : 'pending',
    caption: inboundClosed ? '已冲销' : record.status === 'executed' ? '已执行' : record.status === 'approved' ? partialInbound ? '部分入库，待续收' : '待执行'
      : interrupted ? '已中止' : '批准后执行', event: eventFor('execute') })
  const summary = inboundClosed ? '原入库已冲销，剩余数量已关闭，不能继续入库。' : record.status === 'submitted' ? `当前待办：${record.steps[record.current_step]?.name ?? '审批'}`
    : record.status === 'approved' ? partialInbound ? '审批已完成，已入库数量可使用；剩余数量到货后继续入库。' : '审批已完成，请在业务页面执行对应操作。'
      : record.status === 'executed' ? '审批与业务执行均已完成。'
        : interrupted ? '本次审批已中止，重新送审后重新审批。' : '提交后进入审批流程。'
  return { label: inboundClosed ? '已冲销' : statusLabels[record.status], summary, completed: record.current_step, nodes }
}


export function documentApprovalEventLabel(event: DocumentApprovalEvent): string {
  return event.action === 'approve' ? event.step_name || '批准'
    : { submit: '送审', reject: '驳回', withdraw: '撤回', execute: '执行' }[event.action]
}

export function documentApprovalGenerations(record: DocumentApprovalRecord): number[] {
  // 按轮次归档，不丢失早期送审；草稿保留零轮入口，但不虚构历史轮次。
  return [...new Set([record.generation, ...record.events.map(event => event.generation)])].sort((a, b) => b - a)
}

export function documentApprovalRound(record: DocumentApprovalRecord, generation: number) {
  const events = record.events.filter(event => event.generation === generation)
  const isCurrent = generation === record.generation
  const nodes: ApprovalProgressNode[] = []
  // 旧轮次没有完整模板字段，只根据事件中的步骤和名称绘制，不能套用最新模板补造未办理步骤。
  if (!isCurrent) {
    for (const event of events) {
      const key = event.action === 'approve' || event.action === 'reject' ? `step-${event.step}`
        : event.action === 'withdraw' ? 'withdraw' : event.action
      if (nodes.some(node => node.key === key)) continue
      nodes.push({ key, name: key.startsWith('step-') ? event.step_name || `审批步骤 ${event.step + 1}`
        : key === 'execute' ? '业务执行' : documentApprovalEventLabel(event), role: null, event,
        state: event.action === 'reject' ? 'rejected' : event.action === 'withdraw' ? 'withdrawn' : 'completed',
        caption: event.action === 'reject' ? '已驳回' : event.action === 'withdraw' ? '已撤回' : '已完成' })
    }
  }
  const last = events.at(-1)
  const previousLabel = last?.action === 'withdraw' ? '已撤回' : last?.action === 'reject' ? '已驳回'
    : last?.action === 'execute' ? '已执行' : '历史记录'
  const progress = isCurrent ? documentApprovalProgress(record) : {
    nodes, label: previousLabel, completed: events.filter(event => event.action === 'approve').length,
    summary: '仅展示当时实际发生的节点；下方单据正文为当前送审内容。'
  }
  return { ...progress, generation, isCurrent, events,
    nodes: progress.nodes.map(node => ({ ...node, events: events.filter(event => {
      if (event.action === 'submit') return node.key === 'submit'
      if (event.action === 'execute') return node.key === 'execute'
      if (event.action === 'withdraw') {
        // 本轮撤回关联中止位置；旧轮次缺少当时完整模板，使用独立撤回节点保留事实。
        return node.key === (isCurrent ? event.step < record.steps.length ? `step-${event.step}` : 'execute' : 'withdraw')
      }
      return node.key === `step-${event.step}`
    }) })) }
}

export function documentApprovalDefaultNode(round: ReturnType<typeof documentApprovalRound>): string {
  return round.nodes.find(node => node.state === 'current' || node.state === 'rejected' || node.state === 'withdrawn')?.key
    ?? round.nodes.at(-1)?.key ?? ''
}
