import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { usePiniaAppStore } from '../app-store'
import type { MaterialFlowCreate, MaterialFlowDocument, MaterialFlowExecute, MaterialFlowKind, MaterialFlowLots,
  MaterialFlowPage, MaterialFlowQuery, MaterialFlowTarget, MaterialFlowWrite, WorkOrderMaterialFlow } from '../../../../shared/material-flow-api'
import { validateMaterialFlowDocument } from '../../../../shared/material-flow-api'
import { displayError } from '../../utils/formatters'

export const materialFlowLabels = { dispatch: '生产发料', receipt: '生产领料', exchange: '生产换料', return: '生产退料' } as const
export const materialFlowRoutes = { dispatch: 'productionDispatches', receipt: 'productionReceipts', exchange: 'productionExchanges', return: 'productionReturns' } as const
export const materialFlowApprovalTypes = { dispatch: 'MaterialDispatch', exchange: 'MaterialExchange', return: 'ProductionMaterialReturn' } as const
export const materialFlowPermission = { dispatch: 'material_dispatch', receipt: 'material_receipt', exchange: 'material_exchange', return: 'material_flow_return' } as const
export const materialFlowStatuses = { draft: '待处理', partial: '部分完成', completed: '已完成', closed: '余额已关闭', reversed: '已冲销' } as const
export function materialFlowStatusLabel(kind: MaterialFlowKind, status: string): string {
  // 发出完成不等于生产已收到；各页面使用各自的业务进度词汇。
  const states = {
    dispatch: { draft: '待发料', partial: '部分发出', completed: '已发完' },
    receipt: { draft: '待签收', partial: '部分签收', completed: '交接完成' },
    exchange: { draft: '待换料', partial: '换料处理中', completed: '换料完成' },
    return: { draft: '待接收', partial: '部分接收', completed: '接收完成' }
  }
  return states[kind][status as 'draft' | 'partial' | 'completed'] ?? materialFlowStatuses[status as keyof typeof materialFlowStatuses] ?? status
}
export interface FlowDraftRow { material_id: number; source_key: string; quantity: string; disposal: 'physical' | 'loss'; evidence: string; exchange_line_id?: number; compact?: boolean }
export interface FlowDraft { work_order_id: number; warehouse_id: number; reference: string; reason: string; note: string; request_id: string; submitted_signature?: string; rows: FlowDraftRow[] }
export function flowRequestId(): string { return crypto.randomUUID() }
export function newFlowDraft(orderId = 0): FlowDraft {
  return { work_order_id: orderId, warehouse_id: 1, reference: '', reason: '', note: '', request_id: flowRequestId(), rows: [] }
}

// 独立 Pinia 领域模块保存四页数据与草稿，所有入口使用相同的权限、会话和防重边界。
export const useMaterialFlowStore = defineStore('production-material-flow', () => {
  const app = usePiniaAppStore()
  const pages = ref<Record<string, MaterialFlowPage>>({})
  const orders = ref<Record<number, WorkOrderMaterialFlow>>({})
  const documents = ref<Record<string, MaterialFlowDocument>>({})
  const drafts = ref<Partial<Record<MaterialFlowKind, FlowDraft>>>({})
  const loading = ref<Record<string, boolean>>({}), busy = ref(false), error = ref('')
  // 正文缓存仅用于稳定呈现；每条读取自己的就绪和错误状态才决定能否展开、继续业务操作。
  const readReady = ref<Record<string, boolean>>({}), readErrors = ref<Record<string, string>>({})
  const available = computed(() => !!app.user && !app.connectionLost && app.can('material_flow.view'))
  let owner = 0
  let writeTicket = 0
  const reads = new Map<string, number>()
  // 集合排序使用副本，例行快照只调整角色或权限顺序时不能清掉草稿与正在等待的弹窗。
  watch(() => `${app.server?.id}:${app.server?.fingerprint}:${app.user?.id}:${app.user?.roles?.slice().sort().join('|')}:${app.user?.permissions.slice().sort().join('|')}`, () => {
    // 同账号例行刷新不清空；换服务器、换号或权限变化时，旧响应和草稿立即失效。
    owner++; writeTicket++; reads.clear(); pages.value = {}; orders.value = {}; documents.value = {}; drafts.value = {}; loading.value = {}; readReady.value = {}; readErrors.value = {}; error.value = ''; busy.value = false
  }, { flush: 'sync' })
  watch(() => app.connectionLost, () => {
    // 断线只废弃旧响应与旧写锁，草稿及防重标识保留，重连后允许安全重试。
    owner++; writeTicket++; reads.clear(); loading.value = {}; busy.value = false
    // 重连不能把断线前的正文重新视为当前依据，必须重新读取成功才恢复该 key 的可操作状态。
    readReady.value = Object.fromEntries(Object.keys(readReady.value).map(key => [key, false])); readErrors.value = {}
  }, { flush: 'sync' })
  function ensure(permission = 'material_flow.view'): void {
    if (!window.nexora || !available.value || !app.can(permission)) throw Error('当前账号或连接状态不允许此操作，请重新读取单据。')
  }
  async function read<T>(key: string, call: () => Promise<T>, accept: (result: T) => void): Promise<T | undefined> {
    const session = owner, ticket = (reads.get(key) ?? 0) + 1; reads.set(key, ticket)
    readReady.value[key] = false; readErrors.value[key] = ''
    try {
      ensure(); loading.value[key] = true; error.value = ''
      const result = await call()
      if (owner !== session || reads.get(key) !== ticket || !available.value) return
      accept(result); readReady.value[key] = true; return result
    } catch (cause) {
      if (owner === session && reads.get(key) === ticket) error.value = readErrors.value[key] = displayError(cause)
    }
    finally { if (owner === session && reads.get(key) === ticket) loading.value[key] = false }
  }
  function key(target: MaterialFlowTarget): string { return `${target.kind}:${target.id}` }
  function orderKey(orderId: number): string { return `order:${orderId}` }
  function lotsKey(target: MaterialFlowTarget): string { return `lots:${key(target)}` }
  function cancelRead(scope: string): void {
    // 取消不删除可见缓存，也不修改草稿；代次持续递增，旧 finally 不能解除重新打开的读取状态。
    reads.set(scope, (reads.get(scope) ?? 0) + 1)
    loading.value[scope] = false; readReady.value[scope] = false; readErrors.value[scope] = ''
  }
  function cancelDocument(target: MaterialFlowTarget): void {
    cancelRead(key(target)); cancelRead(lotsKey(target))
  }
  function pageKey(kind: MaterialFlowKind, orderId?: number): string { return `${kind}:order:${orderId ?? 0}` }
  async function query(input: MaterialFlowQuery): Promise<void> {
    const scope = pageKey(input.kind, input.work_order_id)
    // 查询失败清掉旧页，避免把上一筛选结果误认为当前结果。
    delete pages.value[scope]
    await read(scope, () => window.nexora!.callApi('materialFlowQuery', input), result => { pages.value[scope] = result })
  }
  function loadOrder(orderId: number): Promise<WorkOrderMaterialFlow | undefined> {
    return read(orderKey(orderId), () => window.nexora!.callApi('workOrderMaterialFlow', { orderId }), result => { orders.value[orderId] = result })
  }
  function loadDocument(target: MaterialFlowTarget): Promise<MaterialFlowDocument | undefined> {
    // 锁定本次目标；相同目标刷新保留正文，换单仅查询新 key，不借用上一单的缓存。
    const snapshot = { ...target }, scope = key(snapshot)
    return read(scope, () => window.nexora!.callApi('materialFlowDetail', snapshot), result => { documents.value[scope] = result })
  }
  function loadLots(target: MaterialFlowTarget): Promise<MaterialFlowLots | undefined> {
    const snapshot = { ...target }
    return read(lotsKey(snapshot), () => window.nexora!.callApi('materialFlowLots', snapshot), () => {})
  }
  async function write(permission: string, call: () => Promise<MaterialFlowDocument>): Promise<MaterialFlowDocument | undefined> {
    if (busy.value || app.busy) return
    const session = owner, ticket = ++writeTicket
    try {
      ensure(permission); busy.value = true; error.value = ''
      const result = await call()
      if (owner !== session || !available.value || !app.can(permission)) return
      validateMaterialFlowDocument(result)
      // 写入响应已经是新版本；废弃更早的详情和批次读取，防止旧读覆盖服务端刚确认的事实。
      cancelDocument(result); documents.value[key(result)] = result; readReady.value[key(result)] = true
      // 服务端已确认写入成功；后续快照刷新失败不能伪装成写入失败并诱导重复执行。
      let refreshFailed = !(await loadOrder(result.work_order_id))
      try { await app.refreshData() } catch { refreshFailed = true }
      if (owner !== session) return
      app.notice = `${materialFlowLabels[result.kind]}已更新。${refreshFailed ? '部分数据刷新失败，请刷新查看最新结果。' : ''}`
      return result
    } catch (cause) { if (owner === session) error.value = displayError(cause) }
    finally { if (writeTicket === ticket) busy.value = false }
  }
  function create(input: MaterialFlowCreate): Promise<MaterialFlowDocument | undefined> {
    return write(`${materialFlowPermission[input.kind]}.create`, () => window.nexora!.callApi('createMaterialFlow', input))
  }
  function update(input: MaterialFlowCreate & { id: number; version: number }): Promise<MaterialFlowDocument | undefined> {
    return write(`${materialFlowPermission[input.kind]}.create`, () => window.nexora!.callApi('updateMaterialFlow', input))
  }
  function execute(input: MaterialFlowExecute, handover = false): Promise<MaterialFlowDocument | undefined> {
    const permission = input.kind === 'receipt' ? handover ? 'material_receipt.handover_return' : 'material_receipt.sign' : `${materialFlowPermission[input.kind]}.post`
    return write(permission, () => window.nexora!.callApi(handover ? 'handoverReturnMaterialFlow' : 'executeMaterialFlow', input))
  }
  function close(input: MaterialFlowWrite): Promise<MaterialFlowDocument | undefined> {
    return write(`${materialFlowPermission[input.kind]}.close`, () => window.nexora!.callApi('closeMaterialFlow', input))
  }
  function reverse(input: MaterialFlowWrite): Promise<MaterialFlowDocument | undefined> {
    return write(`${materialFlowPermission[input.kind]}.reverse`, () => window.nexora!.callApi('reverseMaterialFlow', input))
  }
  function replacement(input: MaterialFlowWrite): Promise<MaterialFlowDocument | undefined> {
    return write('material_dispatch.create', () => window.nexora!.callApi('createExchangeDispatch', input))
  }
  function draft(kind: MaterialFlowKind, orderId?: number): FlowDraft {
    return drafts.value[kind] ?? (drafts.value[kind] = newFlowDraft(orderId))
  }
  return { pages, orders, documents, drafts, loading, readReady, readErrors, busy, error, available, query, loadOrder, loadDocument, loadLots,
    create, update, execute, close, reverse, replacement, draft, pageKey, key, orderKey, lotsKey, cancelRead, cancelDocument }
})
