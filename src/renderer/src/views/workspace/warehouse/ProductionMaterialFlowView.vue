<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import WorkspaceMaterialName from '../../../components/workspace/WorkspaceMaterialName.vue'
import { materialParameterIndex } from '../../../utils/material-parameter-source'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import DocumentApprovalPanel from '../../../components/workspace/DocumentApprovalPanel.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { useMaterialFlowStore, materialFlowLabels, materialFlowPermission, materialFlowApprovalTypes,
  materialFlowStatusLabel, materialFlowRoutes, flowRequestId, newFlowDraft } from '../../../store/modules/material-flow-store'
import type { FlowDraftRow } from '../../../store/modules/material-flow-store'
import type { MaterialFlowDocument, MaterialFlowExecutionLine, MaterialFlowKind, MaterialFlowLine, MaterialFlowLots, MaterialFlowSource } from '../../../../../shared/material-flow-api'
import type { WorkspaceTableColumn } from '../../../utils/table-columns'
import type { WorkspaceSearchFilterField } from '../../../utils/workspace-search-filters'
import type { LotEditorPart } from '../../../utils/lot-allocation'
import { documentLabel } from '../../../../../shared/document-numbering'
import { materialFlowExecutionHint, materialFlowExecutionLabels } from '../../../utils/material-flow-progress'
import { routeByKey } from '../../../router/workspace-routes'
import { captureDialogOrigin } from '../../../utils/dialog-origin'

// 仓库四页和工单内嵌区复用同一业务组件；所在页面不授予额外操作权限。
const props = withDefaults(defineProps<{ kind: MaterialFlowKind; workOrderId?: number; embedded?: boolean }>(), { embedded: false })
const app = usePiniaAppStore(), flow = useMaterialFlowStore(), route = useRoute(), router = useRouter()
const { pages, orders, documents, loading, readErrors, readReady, busy, error, available } = storeToRefs(flow)
const { workOrders, warehouses, materials, materialCategories, connectionLost } = storeToRefs(app)
// 生产详情自带资料供业务只读账号使用；已有全局缓存仅兼容旧服务端。
const materialById = computed(() => materialParameterIndex(materials.value))
const query = ref(''), filters = ref({ status: '', warehouse: 0, person: 0, from: '', to: '' }), page = ref(1), pageSize = ref(20)
const scopeOrder = computed(() => props.workOrderId || (Number(route.query.work_order_id) || undefined))
const pageKey = computed(() => flow.pageKey(props.kind, scopeOrder.value))
const result = computed(() => pages.value[pageKey.value])
const title = computed(() => materialFlowLabels[props.kind])
const disabled = computed(() => busy.value || app.busy || connectionLost.value || !available.value)
// 同一组件承载四个页面，来源按业务种类隔离，不借用其他页面的最后点击。
const createOriginKey = computed(() => `ProductionMaterialFlowView:${props.kind}:create`)
const detailOriginKey = computed(() => `ProductionMaterialFlowView:${props.kind}:detail`)
const canCreate = computed(() => props.kind !== 'receipt' && app.can(`${materialFlowPermission[props.kind]}.create`))
const summaries = computed(() => [
  { key: '', label: '全部', count: Object.values(result.value?.summary ?? {}).reduce((sum, value) => sum + value, 0), hint: '按当前搜索条件统计全部匹配单据' },
  ...(['draft', 'partial', 'completed', 'closed'] as const).map(key => ({ key, label: materialFlowStatusLabel(props.kind, key), count: result.value?.summary[key] ?? 0,
    hint: `查看${materialFlowStatusLabel(props.kind, key)}单据`, tone: key === 'completed' ? 'success' as const : key === 'closed' ? 'neutral' as const : 'pending' as const }))
])
const filterFields = computed<WorkspaceSearchFilterField[]>(() => [
  { key: 'status', kind: 'select', label: '状态', options: [{ value: '', label: '全部状态' }, ...(['draft', 'partial', 'completed', 'closed', 'reversed'] as const).map(value => ({ value, label: materialFlowStatusLabel(props.kind, value) }))] },
  { key: 'warehouse', kind: 'select', label: '仓库', options: [{ value: 0, label: '全部仓库' }, ...(result.value?.warehouses ?? warehouses.value).map(item => ({ value: item.id, label: item.name }))] },
  // 人员查询同时包含建单和实际办理人员，标签与服务端筛选范围保持一致。
  { key: 'person', kind: 'select', label: '相关人员', options: [{ value: 0, label: '全部人员' }, ...(result.value?.actors ?? []).map(item => ({ value: item.id, label: item.name }))] },
  { key: 'from', kind: 'date', label: '开始日期', maxKey: 'to' }, { key: 'to', kind: 'date', label: '结束日期', minKey: 'from' }
])
const dateIssue = computed(() => filters.value.from && filters.value.to && filters.value.from > filters.value.to ? '开始日期不能晚于结束日期。' : '')
async function refresh(): Promise<void> {
  if (!available.value || dateIssue.value) return
  await flow.query({ kind: props.kind, page: page.value, page_size: pageSize.value, q: query.value,
    status: filters.value.status || undefined, warehouse_id: filters.value.warehouse || undefined,
    created_by: filters.value.person || undefined, date_from: filters.value.from || undefined, date_to: filters.value.to || undefined,
    work_order_id: scopeOrder.value, timezone_offset_minutes: new Date().getTimezoneOffset() })
}
let timer: ReturnType<typeof setTimeout> | undefined
watch([query, filters, scopeOrder, () => props.kind], () => { page.value = 1; clearTimeout(timer); timer = setTimeout(() => void refresh(), 180) }, { deep: true })
watch(available, value => { if (value) void refresh() }, { immediate: true })

function resetFilters(): void { query.value = ''; filters.value = { status: '', warehouse: 0, person: 0, from: '', to: '' } }
function paginate(next: number, size: number): void { page.value = next; pageSize.value = size; void refresh() }
const columns: readonly WorkspaceTableColumn[] = [
  { key: 'document', title: '本单 / 时间', width: '210' }, { key: 'order', title: '工单 / 产品', width: '200' },
  { key: 'source', title: '来源 / 仓库 / 人员', width: '200' }, { key: 'materials', title: '物料明细', width: '260' },
  { key: 'progress', title: '处理进度', width: '220' }, { key: 'actions', title: '操作', width: '85', align: 'center' }
]
const lineColumns = computed<readonly WorkspaceTableColumn[]>(() => [
  { key: 'material', title: '物料 / 来源', width: '360' }, { key: 'unit', title: '单位', width: '75' },
  { key: 'quantity', title: activeKind.value === 'receipt' ? '仓库发出数量' : activeKind.value === 'dispatch' ? '计划数量' : '申请数量', width: '120' }, { key: 'progress', title: '累计进度', width: '250' }
])
const draftColumns = computed<WorkspaceTableColumn[]>(() => [
  { key: 'material', title: props.kind === 'dispatch' ? '物料 / 资料' : '物料 / 已签收来源', width: '440' }, { key: 'unit', title: '单位', width: '75' },
  { key: 'quantity', title: '本次数量', width: '150' }, ...(props.kind === 'exchange' ? [{ key: 'disposal', title: '旧料处理 / 损耗依据', width: '250' }] : []),
  { key: 'actions', title: '操作', width: '75' }
])
const createOpen = ref(false), editTarget = ref<{ id: number; version: number } | null>(null)
const createLoading = ref(false), createError = ref('')
let createGeneration = 0, createOrderId = 0
const createDisabled = computed(() => disabled.value || createLoading.value || !!createError.value
  || !!draft.value.work_order_id && !readReady.value[`order:${draft.value.work_order_id}`])
const draft = computed(() => flow.draft(props.kind, scopeOrder.value))
const order = computed(() => orders.value[draft.value.work_order_id])
const editingReplacement = computed(() => !!editTarget.value && draft.value.rows.some(row => row.exchange_line_id))
// 编辑草稿时，将本单原先占用的数量加回可编辑额度；不借用其他申请的预留。
function addQuantity(left: string, right: string): string {
  const milli = (value: string) => { const [whole, fraction = ''] = value.split('.'); return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0')) }
  const total = milli(left) + milli(right); return `${total / 1000n}.${(total % 1000n).toString().padStart(3, '0')}`
}
const formSources = computed(() => {
  const sources = (order.value?.sources ?? []).map(source => ({ ...source }))
  const original = editTarget.value ? documents.value[`${props.kind}:${editTarget.value.id}`] : undefined
  for (const line of original?.lines ?? []) {
    if (!line.source_receipt_line_id && !line.legacy_issue_line_id) continue
    const existing = sources.find(source => source.source_receipt_line_id === line.source_receipt_line_id && source.legacy_issue_line_id === line.legacy_issue_line_id)
    if (existing) existing.available_quantity = addQuantity(existing.available_quantity, line.quantity)
    else sources.push({ ...line, source_document_no: original?.source_document_no || '原单已签收来源', available_quantity: line.quantity, warehouse_id: original?.warehouse_id })
  }
  return sources.filter(source => !source.warehouse_id || source.warehouse_id === draft.value.warehouse_id)
})
const choices = computed(() => order.value?.lines.map(line => materials.value.find(item => item.id === line.material_id)
  ?? { id: line.material_id, sku: line.sku, name: line.material_name, unit: line.unit }) ?? [])
const createOrderOptions = computed(() => (result.value?.work_orders ?? workOrders.value).filter(item => ['released', 'in_progress'].includes(item.status)
  && (!scopeOrder.value || item.id === scopeOrder.value)).map(item => ({ value: item.id, label: `${documentLabel(item)} · ${item.product_name}` })))
function sourceKey(source: MaterialFlowSource): string { return source.source_receipt_line_id ? `receipt:${source.source_receipt_line_id}` : `legacy:${source.legacy_issue_line_id}` }
function rowSource(row: FlowDraftRow): MaterialFlowSource | undefined { return formSources.value.find(source => sourceKey(source) === row.source_key) }
function rowLimit(row: FlowDraftRow): string {
  if (props.kind !== 'dispatch') return rowSource(row)?.available_quantity ?? '0'
  const original = editTarget.value ? documents.value[`${props.kind}:${editTarget.value.id}`]?.lines.find(line => line.material_id === row.material_id && line.exchange_line_id === (row.exchange_line_id ?? null))?.quantity ?? '0' : '0'
  // 补发仅使用对应换料行的已确认损坏额度；不能借用普通工单需求。
  if (row.exchange_line_id) {
    const source = order.value?.exchanges.flatMap(item => item.lines).find(line => line.id === row.exchange_line_id)
    return addQuantity(source?.replacement_available_quantity ?? '0', original)
  }
  const remaining = order.value?.lines.find(line => line.material_id === row.material_id)?.dispatchable_quantity ?? '0'
  return addQuantity(remaining, original)
}
function rowUnit(row: FlowDraftRow): string { return choices.value.find(item => item.id === row.material_id)?.unit ?? '—' }
function changeMaterial(row: FlowDraftRow): void {
  row.source_key = ''; row.quantity = props.kind === 'dispatch' ? rowLimit(row) : '1'
  if (props.kind === 'dispatch') return
  const first = formSources.value.find(source => source.material_id === row.material_id && Number(source.available_quantity) > 0)
  if (first) { row.source_key = sourceKey(first); row.quantity = first.available_quantity }
}
function addRow(): void { draft.value.rows.push({ material_id: 0, source_key: '', quantity: '1', disposal: 'physical', evidence: '' }) }
function cancelCreateRead(): void {
  createGeneration++
  if (createOrderId) flow.cancelRead(`order:${createOrderId}`)
  createOrderId = 0; createLoading.value = false
}
function closeCreate(show: boolean, force = false): void {
  if (!force && (busy.value || app.busy)) return
  createOpen.value = show
  if (!show) cancelCreateRead()
}
async function prepareCreateOrder(id: number, resetRows: boolean): Promise<boolean> {
  cancelCreateRead()
  if (!id) { createError.value = ''; return true }
  const ticket = createGeneration, input = draft.value
  createOrderId = id; createLoading.value = true; createError.value = ''
  const loaded = await flow.loadOrder(id)
  if (ticket !== createGeneration || !createOpen.value || !available.value || draft.value !== input) return false
  createOrderId = 0
  if (!loaded) { createError.value = readErrors.value[`order:${id}`] || '工单材料资料读取失败，请重新打开后重试。'; createLoading.value = false; return false }
  if (resetRows) {
    const warehouse = (result.value?.work_orders ?? workOrders.value).find(item => item.id === id)?.warehouse_id
    if (warehouse) input.warehouse_id = warehouse
    input.rows = props.kind === 'dispatch' ? loaded.lines.filter(line => Number(line.dispatchable_quantity) > 0)
      .map(line => ({ material_id: line.material_id, source_key: '', quantity: line.dispatchable_quantity, disposal: 'physical', evidence: '' }))
      : [{ material_id: 0, source_key: '', quantity: '1', disposal: 'physical', evidence: '' }]
  }
  createLoading.value = false
  return true
}
async function chooseOrder(id: number): Promise<void> {
  draft.value.work_order_id = id; draft.value.rows = []
  await prepareCreateOrder(id, true)
}
async function openCreate(event?: Event): Promise<void> {
  if (!canCreate.value || disabled.value) return
  if (event) captureDialogOrigin(createOriginKey.value, event)
  editTarget.value = null; createError.value = ''; createOpen.value = true
  if (scopeOrder.value && (draft.value.work_order_id !== scopeOrder.value || !draft.value.rows.length)) await chooseOrder(scopeOrder.value)
  else await prepareCreateOrder(draft.value.work_order_id, !draft.value.rows.length)
}
async function editDraft(event?: Event): Promise<void> {
  const current = detail.value
  if (!current || detailDisabled.value || !canCreate.value || current.kind === 'receipt' || current.kind !== props.kind || current.status !== 'draft') return
  if (event) captureDialogOrigin(createOriginKey.value, event)
  // 先建立可取消的打开意图，完整额度到齐前不改写已有草稿，也不关闭来源详情。
  cancelCreateRead()
  const ticket = createGeneration
  createOrderId = current.work_order_id; createLoading.value = true; createError.value = ''; createOpen.value = true
  const loaded = await flow.loadOrder(current.work_order_id)
  if (ticket !== createGeneration || !createOpen.value || !available.value) return
  createOrderId = 0
  if (!loaded) { createError.value = readErrors.value[`order:${current.work_order_id}`] || '工单材料资料读取失败，请重新打开后重试。'; createLoading.value = false; return }
  flow.drafts[props.kind] = { work_order_id: current.work_order_id, warehouse_id: current.warehouse_id,
    reference: current.reference, reason: current.reason, note: current.note, request_id: flowRequestId(),
    rows: current.lines.map(line => ({ material_id: line.material_id,
      source_key: line.source_receipt_line_id ? `receipt:${line.source_receipt_line_id}` : line.legacy_issue_line_id ? `legacy:${line.legacy_issue_line_id}` : '',
      quantity: line.quantity, disposal: line.disposal ?? 'physical', evidence: line.evidence ?? '', exchange_line_id: line.exchange_line_id ?? undefined })) }
  editTarget.value = { id: current.id, version: current.version }; closeDetail(false); createLoading.value = false
}
function captureSavedDetailOrigin(event?: Event): void {
  if (!event) return
  // 原生 submitter 保留键盘提交与鼠标保存的真实入口，异步保存完成后不再读取事件对象。
  captureDialogOrigin(detailOriginKey.value, (event as SubmitEvent).submitter ?? event.target as Element | null)
}
async function saveDraft(): Promise<void> {
  if (props.kind === 'receipt' || !createOpen.value || createDisabled.value || !canCreate.value) return
  const ticket = createGeneration
  const input = draft.value
  const lines = input.rows.map(row => {
    const source = props.kind === 'dispatch' ? undefined : rowSource(row)
    return { work_order_line_id: order.value?.lines.find(line => line.material_id === row.material_id)?.work_order_line_id ?? 0,
      quantity: row.quantity, ...(source?.source_receipt_line_id ? { source_receipt_line_id: source.source_receipt_line_id } : {}),
      ...(source?.legacy_issue_line_id ? { legacy_issue_line_id: source.legacy_issue_line_id } : {}),
      ...(props.kind === 'dispatch' && row.exchange_line_id ? { exchange_line_id: row.exchange_line_id } : {}),
      ...(props.kind === 'exchange' ? { disposal: row.disposal, evidence: row.evidence } : {}) }
  })
  const content = { kind: props.kind, work_order_id: input.work_order_id, warehouse_id: input.warehouse_id,
    reference: input.reference, reason: input.reason, note: input.note, lines }
  // 只有送往服务端的真实内容改变才轮换防重标识，展开资料与失败重试不改变它。
  const signature = JSON.stringify(content)
  if (input.submitted_signature && input.submitted_signature !== signature) input.request_id = flowRequestId()
  input.submitted_signature = signature
  const payload = { ...content, request_id: input.request_id }
  const saved = editTarget.value ? await flow.update({ ...payload, ...editTarget.value }) : await flow.create(payload)
  if (saved && ticket === createGeneration && createOpen.value) {
    closeCreate(false); flow.drafts[props.kind] = newFlowDraft(scopeOrder.value)
    await openDetail(saved); await refresh()
  }
}

const activeId = ref(0), activeKind = ref<MaterialFlowKind>(props.kind), detailOpen = ref(false)
const detailLoading = ref(false), detailError = ref(''), operationLoading = ref(false), operationError = ref('')
let detailGeneration = 0, detailOrderId = 0, operationGeneration = 0
const detailKey = computed(() => `${activeKind.value}:${activeId.value}`)
const detail = computed(() => documents.value[`${activeKind.value}:${activeId.value}`])
function sourceLinks(item: MaterialFlowDocument) {
  const links = [item, ...item.lines].filter(source => source.source_document_kind && source.source_document_id)
    .map(source => ({ kind: source.source_document_kind!, id: source.source_document_id!, label: source.source_document_no || `#${source.source_document_id}` }))
  return links.filter((link, index) => links.findIndex(other => other.kind === link.kind && other.id === link.id) === index)
}
const relatedDocuments = computed(() => {
  if (!detail.value) return []
  const summary = orders.value[detail.value.work_order_id]
  if (!summary) return []
  return [...summary.dispatches, ...summary.receipts, ...summary.exchanges, ...summary.returns].filter(item =>
    [item, ...item.lines].some(source => source.source_document_kind === detail.value?.kind && source.source_document_id === detail.value?.id))
})
const approvalType = computed(() => detail.value ? detail.value.kind === 'receipt' ? operation.value === 'reverse' ? 'MaterialReceipt' : null : materialFlowApprovalTypes[detail.value.kind] : null)
const approvalReady = computed(() => !!detail.value && !!approvalType.value && app.documentApprovalTarget?.document_type === approvalType.value
  && app.documentApprovalTarget.document_id === detail.value.id && app.documentApprovalRecord?.document_type === approvalType.value
  && app.documentApprovalRecord.document_id === detail.value.id && app.documentApprovalRecord.intent === (operation.value === 'reverse' ? 'reverse' : 'execute')
  && app.documentApprovalTarget.intent === app.documentApprovalRecord.intent && !app.documentApprovalLoading && !app.documentApprovalError)
const executionHint = computed(() => detail.value && app.documentApprovalRecord?.intent === 'execute' ? materialFlowExecutionHint(detail.value) : undefined)
const approved = computed(() => !detailDisabled.value && (detail.value?.kind === 'receipt' || approvalReady.value && app.documentApprovalRecord?.intent === 'execute' && ['approved', 'executed'].includes(app.documentApprovalRecord?.status ?? '') && app.documentApprovalRecord?.content_matches))
const actionable = computed(() => !!detail.value && ['draft', 'partial'].includes(detail.value.status))
const operation = ref<'execute' | 'handover' | 'close' | 'reverse' | ''>('')
const operationReason = ref(''), requestId = ref(flowRequestId()), lots = ref<MaterialFlowLots>({ lines: [] })
const operationVersion = ref(0)
const quantities = ref<Record<number, string>>({}), allocations = ref<Record<number, LotEditorPart[]>>({})
watch(() => JSON.stringify([quantities.value, allocations.value, operationReason.value]), () => { requestId.value = flowRequestId() }, { flush: 'sync' })
// 正文可以保留旧画面，但授权只接受当前目标、当前代次和最新读取结果。
const detailDisabled = computed(() => disabled.value || !detailOpen.value || detailLoading.value || operationLoading.value
  || !!detailError.value || !!operationError.value || !detail.value || !readReady.value[detailKey.value]
  || !readReady.value[`order:${detail.value.work_order_id}`] || !!approvalType.value && !approvalReady.value)
const detailReady = computed(() => !detailLoading.value && !operationLoading.value && !app.documentApprovalLoading && !!detail.value)
const detailLoadError = computed(() => detailError.value || operationError.value || (approvalType.value ? app.documentApprovalError : ''))
const executionLabel = computed(() => ({ dispatch: '确认实际发出', receipt: '确认实际签收', exchange: '确认旧料交接', return: '确认退料入库' })[detail.value?.kind ?? props.kind])
const executePermission = computed(() => detail.value?.kind === 'receipt' ? 'material_receipt.sign' : `${materialFlowPermission[detail.value?.kind ?? props.kind]}.post`)
function lineProgress(line: MaterialFlowLine, kind: MaterialFlowKind, status?: string): string {
  if (status === 'closed') return `累计执行 ${line.executed_quantity} · 实收 ${line.received_quantity} · 已关闭余额 ${line.closed_quantity ?? '0'}`
  if (status === 'reversed') return `原申请 ${line.quantity} · 已追加冲销记录`
  if (kind === 'dispatch') return `已发 ${line.executed_quantity} · 已签 ${line.received_quantity} · 待发 ${line.remaining_quantity}`
  if (kind === 'receipt') return `实收 ${line.received_quantity} · 待签 ${line.remaining_quantity}`
  if (kind === 'exchange') return `旧料交接 ${line.executed_quantity} · 新料已发 ${line.dispatched_quantity ?? '0'} · 新料实收 ${line.received_quantity} · 待完成 ${line.remaining_quantity}`
  return `已收 ${line.executed_quantity} · 待收 ${line.remaining_quantity}`
}
function executionMaterial(line: MaterialFlowExecutionLine): MaterialFlowLine | undefined {
  return detail.value?.lines.find(material => material.id === line.line_id)
}
function unregisteredQuantity(line: MaterialFlowExecutionLine): string {
  // 仅正向事实计算未登记批次差额；冲销保留服务端负数与原事实引用，不虚构批次。
  const milli = (value: string): bigint => {
    if (!/^\d+(?:\.\d{1,3})?$/.test(value)) return 0n
    const [whole, fraction = ''] = value.split('.')
    return BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
  }
  const unknown = milli(line.quantity) - (line.lots ?? []).reduce((total, lot) => total + milli(lot.quantity), 0n)
  if (unknown <= 0n || line.reverses_line_id) return ''
  const fraction = (unknown % 1000n).toString().padStart(3, '0').replace(/0+$/, '')
  return `${unknown / 1000n}${fraction ? `.${fraction}` : ''}`
}
function cancelDetailReads(): void {
  detailGeneration++; operationGeneration++
  if (activeId.value) flow.cancelDocument({ kind: activeKind.value, id: activeId.value })
  if (detailOrderId) flow.cancelRead(`order:${detailOrderId}`)
  detailOrderId = 0; detailLoading.value = false; operationLoading.value = false
}
async function readDetail(target: { id: number; kind: MaterialFlowKind }, reloadApproval = true): Promise<void> {
  const ticket = ++detailGeneration
  detailLoading.value = true; detailError.value = ''; operationError.value = ''
  const current = () => ticket === detailGeneration && detailOpen.value && available.value
    && activeId.value === target.id && activeKind.value === target.kind
  try {
    const value = await flow.loadDocument(target)
    if (!current()) return
    if (!value) { detailError.value = readErrors.value[`${target.kind}:${target.id}`] || '单据读取失败，请重新打开后重试。'; return }
    if (reloadApproval && value.kind !== 'receipt') {
      const approved = await app.openDocumentApproval({ document_type: materialFlowApprovalTypes[value.kind], document_id: value.id, intent: operation.value === 'reverse' ? 'reverse' : 'execute' })
      if (!current()) return
      if (!approved) { detailError.value = app.documentApprovalError || '审批记录读取失败，请重新打开后重试。'; return }
    } else if (reloadApproval && operation.value !== 'reverse') app.closeDocumentApproval()
    detailOrderId = value.work_order_id
    const order = await flow.loadOrder(value.work_order_id)
    if (!current()) return
    detailOrderId = 0
    if (!order) detailError.value = readErrors.value[`order:${value.work_order_id}`] || '工单材料资料读取失败，请重新打开后重试。'
  } finally { if (current()) detailLoading.value = false }
}
async function openDetail(target: { id: number; kind: MaterialFlowKind }, event?: Event): Promise<void> {
  if (disabled.value) return
  if (event) captureDialogOrigin(detailOriginKey.value, event)
  // show 持续为 true 的换单也拥有独立代次，取消同一单后重开不能被上一轮响应解除等待。
  cancelDetailReads(); app.closeDocumentApproval()
  detailLoading.value = true; detailError.value = ''; operationError.value = ''; operation.value = ''; requestId.value = flowRequestId()
  activeId.value = target.id; activeKind.value = target.kind; detailOpen.value = true
  await readDetail(target)
}
function closeDetail(show: boolean, force = false): void {
  if (!force && (busy.value || app.busy)) return
  detailOpen.value = show
  if (!show) { cancelDetailReads(); operation.value = ''; app.closeDocumentApproval() }
}
async function refreshDetail(): Promise<void> {
  if (!detailOpen.value || !detail.value || disabled.value) return
  await readDetail({ id: activeId.value, kind: activeKind.value })
  await refresh()
}
watch(() => app.documentApprovalRecord?.version, () => {
  // 审批动作后的业务正文刷新沿用首屏屏障；审批读取本身不会再触发一轮递归读取。
  if (detailOpen.value && detail.value && approvalReady.value && !detailLoading.value && !operationLoading.value)
    void readDetail({ id: activeId.value, kind: activeKind.value }, false)
})
async function prepare(action: typeof operation.value): Promise<void> {
  const target = detail.value
  if (!target || detailDisabled.value || !action) return
  const ticket = ++operationGeneration
  flow.cancelRead(`lots:${target.kind}:${target.id}`)
  operationLoading.value = true; operationError.value = ''
  operation.value = action; operationVersion.value = target.version; operationReason.value = ''; requestId.value = flowRequestId(); quantities.value = {}; allocations.value = {}; lots.value = { lines: [] }
  const current = () => ticket === operationGeneration && detailOpen.value && detail.value?.id === target.id && detail.value.kind === target.kind && available.value
  try {
    if (action === 'reverse') {
      const loaded = await app.openDocumentApproval({ document_type: target.kind === 'receipt' ? 'MaterialReceipt' : materialFlowApprovalTypes[target.kind], document_id: target.id, intent: 'reverse' })
      if (current() && !loaded) operationError.value = app.documentApprovalError || '更正审批读取失败，请关闭后重试。'
    }
    if (action === 'execute' || action === 'handover') {
      for (const line of target.lines) { quantities.value[line.id] = '0'; allocations.value[line.id] = [] }
      const loaded = await flow.loadLots(target)
      if (!current()) return
      if (!loaded) operationError.value = readErrors.value[`lots:${target.kind}:${target.id}`] || '可用批次读取失败，请关闭后重试。'
      else lots.value = loaded
    }
  } finally { if (current()) operationLoading.value = false }
}
const usesLots = computed(() => operation.value === 'execute' || operation.value === 'handover')
function operationLimit(line: MaterialFlowLine): string {
  // 换料总进度按新料签收计算，收旧时则只能处理尚未交接的旧料。
  return detail.value?.kind === 'exchange' ? String(Math.max(0, Math.round((Number(line.quantity) - Number(line.executed_quantity)) * 1000)) / 1000) : line.remaining_quantity
}
const hasExecutableLines = computed(() => detail.value?.lines.some(line => Number(operationLimit(line)) > 0))
function addLot(line: MaterialFlowLine): void { allocations.value[line.id] ??= []; allocations.value[line.id].push({ lot_id: null, quantity: quantities.value[line.id] === '0' ? '' : quantities.value[line.id] }) }
async function cancelOperation(): Promise<void> {
  if (busy.value || app.busy) return
  const target = detail.value, ticket = ++operationGeneration
  if (target) flow.cancelRead(`lots:${target.kind}:${target.id}`)
  operation.value = ''; operationError.value = ''; operationLoading.value = !!target && target.kind !== 'receipt'
  app.closeDocumentApproval()
  if (!target || target.kind === 'receipt') return
  const loaded = await app.openDocumentApproval({ document_type: materialFlowApprovalTypes[target.kind], document_id: target.id, intent: 'execute' })
  if (ticket !== operationGeneration || !detailOpen.value || !available.value) return
  if (!loaded) operationError.value = app.documentApprovalError || '审批记录读取失败，请关闭后重试。'
  operationLoading.value = false
}
async function submitOperation(): Promise<void> {
  const current = detail.value
  if (!current || detailDisabled.value || !operation.value || operation.value === 'reverse' && (!approvalReady.value || app.documentApprovalRecord?.status !== 'approved')) return
  const ticket = detailGeneration
  const input = { kind: current.kind, id: current.id, version: operationVersion.value || current.version, request_id: requestId.value, reason: operation.value === 'reverse' ? app.documentApprovalRecord?.reversal_reason || operationReason.value : operationReason.value }
  let result: MaterialFlowDocument | undefined
  if (operation.value === 'close') result = await flow.close(input)
  else if (operation.value === 'reverse') result = await flow.reverse(input)
  else result = await flow.execute({ ...input, lines: current.lines.filter(line => Number(quantities.value[line.id]) > 0).map(line => ({ line_id: line.id, quantity: quantities.value[line.id],
    ...(usesLots.value && allocations.value[line.id]?.length ? { lots: (allocations.value[line.id] ?? []).map(part => ({ lot_id: part.lot_id ?? 0, quantity: part.quantity })) } : {}) })) }, operation.value === 'handover')
  if (result && ticket === detailGeneration && detailOpen.value) { operation.value = ''; await refreshDetail() }
}
async function createReplacement(event?: Event): Promise<void> {
  if (!detail.value || detailDisabled.value || !approved.value || !app.can('material_dispatch.create')) return
  if (event) captureDialogOrigin(detailOriginKey.value, event)
  const ticket = detailGeneration
  const result = await flow.replacement({ kind: 'exchange', id: detail.value.id, version: detail.value.version, request_id: requestId.value })
  if (result && ticket === detailGeneration && detailOpen.value) { requestId.value = flowRequestId(); await openDetail(result); await refresh() }
}
async function openWorkOrder(item: MaterialFlowDocument, event?: Event): Promise<void> {
  captureDialogOrigin('document-approval', event)
  closeDetail(false)
  await router.push({ path: routeByKey('workOrders').path, query: { document_id: item.work_order_id } })
}
function sessionKey(): string { return `${app.server?.id}:${app.server?.fingerprint}:${app.user?.id}:${[...(app.user?.roles ?? [])].sort().join('|')}:${[...(app.user?.permissions ?? [])].sort().join('|')}` }
async function openLinked(kind: MaterialFlowKind | 'legacy_issue', id: number, event?: Event): Promise<void> {
  if (kind === 'legacy_issue') {
    captureDialogOrigin('document-approval', event)
    const session = sessionKey()
    closeDetail(false)
    await router.push({ path: routeByKey('materialIssues').path })
    // 跨页面等待期间换号或断线，不能在新会话继续打开旧单据。
    if (session !== sessionKey() || !available.value) return
    await app.openDocumentApproval({ document_type: 'MaterialIssue', document_id: id, intent: 'execute' }); return
  }
  if (props.embedded || kind === props.kind) await openDetail({ kind, id }, event)
  else {
    captureDialogOrigin(`ProductionMaterialFlowView:${kind}:detail`, event)
    closeDetail(false)
    await router.push({ path: routeByKey(materialFlowRoutes[kind]).path, query: { document_id: id, work_order_id: scopeOrder.value } })
  }
}
function invalidateDialogs(): void {
  // 账号、服务器或权限失效强制清理；保存中的普通关闭保护不能保留旧身份数据。
  closeCreate(false, true); closeDetail(false, true); editTarget.value = null; activeId.value = 0
  createError.value = ''; detailError.value = ''; operationError.value = ''; lots.value = { lines: [] }
}
watch(sessionKey, invalidateDialogs, { flush: 'sync' })
watch([() => props.kind, scopeOrder], invalidateDialogs, { flush: 'sync' })
watch(available, value => { if (!value) invalidateDialogs() }, { flush: 'sync' })
onBeforeUnmount(() => { clearTimeout(timer); invalidateDialogs() })
watch(() => [route.query.document_id, props.kind], () => { if (!props.embedded && available.value && Number(route.query.document_id) > 0) void openDetail({ kind: props.kind, id: Number(route.query.document_id) }) }, { immediate: true })
</script>

<template>
  <section class="stack material-flow-workspace">
    <!-- 主标题由工作台外壳提供，统计放到同一个标题区，避免重复物料页面标题。 -->
    <Teleport v-if="!embedded" defer to="#workspace-page-summary">
      <WorkspaceSummaryFilters :model-value="filters.status" :options="summaries" hint="当前搜索、仓库、人员与日期范围 · 全部匹配单据" @update:model-value="value => filters.status = value" />
    </Teleport>
    <WorkspaceTable :title="title" :show-title="embedded" :columns="columns" :data="result?.items ?? []" :loading="loading[pageKey]" :error="error" :min-table-width="1120"
      :pagination="{ page: result?.page ?? page, pageSize: result?.page_size ?? pageSize, total: result?.total ?? 0, disabled: disabled }" @page-change="paginate">
      <template #filters><WorkspaceSearchFilters v-model:query="query" v-model:filters="filters" :fields="filterFields" search-label="搜索单据" search-placeholder="单号、工单、产品或物料" :issue="dateIssue" @reset="resetFilters" /></template>
      <template #actions><AppButton :disabled="disabled" @click="refresh">刷新</AppButton><AppButton v-if="canCreate" variant="primary" :disabled="disabled" @click="openCreate">新建{{ title }}</AppButton></template>
      <template #cell-document="{ row }"><strong>{{ row.document_no }}</strong><small>{{ app.localTime(row.created_at) }}</small><span class="pill">{{ materialFlowStatusLabel(row.kind, row.status) }}</span></template>
      <template #cell-order="{ row }"><AppButton v-if="app.can('production.view')" variant="text" @click="openWorkOrder(row, $event)">{{ row.work_order_document_no }}</AppButton><strong v-else>{{ row.work_order_document_no }}</strong><small>{{ row.product_name }}</small></template>
      <template #cell-source="{ row }"><AppButton v-for="source in sourceLinks(row)" :key="`${source.kind}:${source.id}`" variant="text" @click="openLinked(source.kind, source.id, $event)">{{ source.label }}</AppButton><span v-if="!sourceLinks(row).length">{{ row.kind === 'dispatch' ? '工单正常需求' : '按明细来源' }}</span><small>{{ row.warehouse_name }} · {{ row.created_by_name }}</small></template>
      <template #cell-materials="{ row }"><span v-for="line in row.lines" :key="line.id" class="flow-material-line">{{ line.sku }} · {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}</span></template>
      <template #cell-progress="{ row }"><span v-for="line in row.lines" :key="line.id" class="flow-material-line">{{ lineProgress(line, row.kind, row.status) }}</span></template>
      <template #cell-actions="{ row }"><AppButton :disabled="disabled" @click="openDetail(row, $event)">查看</AppButton></template>
      <template #errorActions><AppButton @click="refresh">重试</AppButton></template>
    </WorkspaceTable>

    <WorkspaceDocumentDialog :show="createOpen" :origin-key="createOriginKey" :ready="!createLoading" :load-error="createError" @update:show="closeCreate" @invalidated="invalidateDialogs" @submit.capture="captureSavedDetailOrigin" :title="`${editTarget ? '编辑' : '新建'}${title}`" :data="draft.rows" :columns="draftColumns" :show-add="!editingReplacement" :busy="busy || app.busy" :disabled="createDisabled" :submit-disabled="!draft.rows.length || !draft.work_order_id" @submit="saveDraft" @add-material="addRow">
      <template #basicInfo>
        <label>生产工单<WorkspaceSelect :model-value="draft.work_order_id" :options="[{ value: 0, label: '选择已下达工单', disabled: true }, ...createOrderOptions]" :disabled="!!scopeOrder || editingReplacement" required @update:model-value="chooseOrder" /></label>
        <label>仓库<WorkspaceSelect v-model="draft.warehouse_id" :options="(result?.warehouses ?? warehouses).map(item => ({ value: item.id, label: item.name }))" required /></label>
        <label>参考号<AppInput v-model="draft.reference" maxlength="100" /></label><label>{{ kind === 'dispatch' ? '说明' : '申请原因' }}<AppInput v-model="draft.reason" :required="kind !== 'dispatch'" maxlength="200" /></label>
        <p class="document-basic-extra muted">{{ kind === 'dispatch' ? '按工单剩余正常需求发料；换料补发由对应换料单生成。保存和审批均不扣减库存。' : '仅可选择已签收且未耗用的来源。待退、待换数量会占用可用额度，仓库实际接收后才改变库存。' }}</p>
      </template>
      <template #cell-material="{ row }"><WorkspaceMaterialSelect v-model="row.material_id" :materials="choices" :categories="materialCategories" aria-label="物料" :disabled="editingReplacement" :compact="row.compact !== false" @update:compact="value => row.compact = value" @change="changeMaterial(row)" />
        <WorkspaceSelect v-if="kind !== 'dispatch'" v-model="row.source_key" aria-label="已签收来源" placeholder="选择已签收来源" :options="formSources.filter(source => source.material_id === row.material_id && Number(source.available_quantity) > 0).map(source => ({ value: sourceKey(source), label: `${source.source_document_no} · 可用 ${source.available_quantity} ${source.unit}` }))" @change="row.quantity = rowLimit(row)" />
      </template>
      <template #cell-unit="{ row }">{{ rowUnit(row) }}</template>
      <template #cell-quantity="{ row }"><AppInput v-model="row.quantity" type="number" min="0.001" step="0.001" :max="rowLimit(row)" required aria-label="本次数量" /><small>可用 {{ rowLimit(row) }}</small></template>
      <template #cell-disposal="{ row }"><WorkspaceSelect v-model="row.disposal" aria-label="旧料处理方式" :options="[{ value: 'physical', label: '交回旧料，隔离接收' }, { value: 'loss', label: '完全损耗，无实物' }]" /><AppInput v-if="row.disposal === 'loss'" v-model="row.evidence" placeholder="填写损耗事实和依据，随单审批" aria-label="无实物损耗依据" required maxlength="500" /></template>
      <template #cell-actions="{ row }"><AppButton @click="draft.rows.splice(draft.rows.indexOf(row), 1)">移除</AppButton></template>
      <template #afterLines><p v-if="error" class="flow-error" role="alert">{{ error }}</p></template>
    </WorkspaceDocumentDialog>

    <WorkspaceDocumentDialog :show="detailOpen" :origin-key="detailOriginKey" :ready="detailReady" :load-error="detailLoadError" :disabled="detailDisabled" @invalidated="invalidateDialogs" :title="`${detail ? materialFlowLabels[detail.kind] : title} · ${detail?.document_no ?? '读取中'}`" read-only :data="detail?.lines ?? []" :columns="lineColumns" :busy="busy || app.busy" @update:show="closeDetail">
      <template #beforeBasicInfo><DocumentApprovalPanel v-if="approvalType" part="progress" :execution-hint="executionHint" live-details /><p v-if="error" class="flow-error" role="alert">{{ error }}</p></template>
      <template #basicInfo><template v-if="detail">
        <div class="document-detail-field"><span>生产工单</span><AppButton variant="text" @click="openWorkOrder(detail, $event)">{{ detail.work_order_document_no }} · {{ detail.product_name }}</AppButton></div>
        <div class="document-detail-field"><span>仓库</span><strong>{{ detail.warehouse_name }}</strong></div>
        <div class="document-detail-field"><span>处理状态</span><strong>{{ materialFlowStatusLabel(detail.kind, detail.status) }}</strong></div>
        <div class="document-detail-field"><span>建单人员 / 时间</span><strong>{{ detail.created_by_name }} · {{ app.localTime(detail.created_at) }}</strong></div>
        <div class="document-detail-field"><span>来源单据</span><AppButton v-if="detail.source_document_kind && detail.source_document_id" variant="text" @click="openLinked(detail.source_document_kind, detail.source_document_id, $event)">{{ detail.source_document_no }}</AppButton><strong v-else>{{ detail.source_document_no || (detail.kind === 'dispatch' ? '工单正常需求' : '按明细来源') }}</strong></div>
        <div class="document-detail-field"><span>参考 / 原因</span><strong>{{ detail.reference || '—' }} · {{ detail.reason || '—' }}</strong></div>
      </template></template>
      <template #cell-material="{ row }"><WorkspaceMaterialName :name="`${row.sku} · ${row.material_name}`" :material-id="row.material_id" :material="row.material" :cached-materials="materialById" :categories="materialCategories" /><AppButton v-if="row.source_document_kind && row.source_document_id" variant="text" @click="openLinked(row.source_document_kind, row.source_document_id, $event)">{{ row.source_document_no }}</AppButton><small v-else-if="row.legacy_issue_line_id">原领料来源 #{{ row.legacy_issue_line_id }}</small><small v-else-if="row.source_receipt_line_id">已签收明细 #{{ row.source_receipt_line_id }}</small><small v-if="detail?.kind === 'exchange' && row.disposal">{{ row.disposal === 'loss' ? '无实物损耗' : '旧料隔离接收' }} {{ row.evidence }}</small></template>
      <template #cell-unit="{ row }">{{ row.unit }}</template><template #cell-quantity="{ row }">{{ row.quantity }}</template>
      <template #cell-progress="{ row }">{{ lineProgress(row, detail?.kind ?? kind, detail?.status) }}</template>
      <template #afterLines>
        <section v-if="relatedDocuments.length" class="flow-history"><h3>关联单据</h3><div v-for="item in relatedDocuments" :key="`${item.kind}:${item.id}`"><AppButton variant="text" @click="openDetail(item, $event)">{{ materialFlowLabels[item.kind] }} · {{ item.document_no }}</AppButton><small>{{ materialFlowStatusLabel(item.kind, item.status) }}</small></div></section>
        <section v-if="detail?.executions.length" class="flow-history"><h3>执行记录</h3><div v-for="execution in detail.executions" :key="execution.id">
          <strong>{{ materialFlowExecutionLabels[execution.action] ?? execution.action }} · {{ execution.created_by_name || execution.actor_name }}</strong><small>{{ app.localTime(execution.created_at) }} · {{ execution.reason }}</small>
          <span v-for="line in execution.lines" :key="line.id ?? line.line_id">
            <template v-if="executionMaterial(line)">{{ executionMaterial(line)?.sku }} · {{ executionMaterial(line)?.material_name }}</template><template v-else>物料明细 #{{ line.line_id }}</template>：{{ line.quantity }} {{ executionMaterial(line)?.unit }}<span v-if="line.movement_id"> · 库存流水 #{{ line.movement_id }}</span>
            <small v-for="lot in line.lots" :key="lot.lot_id">批次 {{ lot.code }}：{{ lot.quantity }} {{ executionMaterial(line)?.unit }}</small>
            <small v-if="unregisteredQuantity(line)">未登记批次：{{ unregisteredQuantity(line) }} {{ executionMaterial(line)?.unit }}</small>
            <small v-if="line.reverses_line_id">冲销原执行记录 #{{ line.reverses_line_id }}</small>
          </span>
        </div></section>
        <section v-if="operation && detail" class="flow-operation"><h3>{{ operation === 'close' ? '关闭未执行余额' : operation === 'reverse' ? '审批更正 / 冲销' : operation === 'handover' ? '未签收实物退回仓库' : executionLabel }}</h3>
          <p class="muted">{{ operation === 'handover' ? '只登记已经实际回仓的未签收物料；不会把未收到的差额自动计入库存。' : operation === 'execute' && detail.kind === 'receipt' ? '按本次实际收到数量签收，余量继续保留待签；此操作不会再次扣减仓库库存。' : operation === 'close' ? '仅关闭尚未执行的余额，已发生的出入库和签收记录全部保留。' : '每次处理独立保存数量、人员、时间与批次，提交前请核对实际实物。' }}</p>
          <template v-if="operation === 'execute' || operation === 'handover'"><div v-for="line in detail.lines.filter(item => Number(operationLimit(item)) > 0)" :key="line.id" class="flow-execute-line">
            <label>{{ line.sku }} · {{ line.material_name }} · 本次{{ operation === 'handover' ? '交回' : '实际' }}数量（最多 {{ operationLimit(line) }} {{ line.unit }}）<AppInput v-model="quantities[line.id]" type="number" min="0" step="0.001" :max="operationLimit(line)" /></label>
            <WorkspaceLotLineEditor v-if="usesLots && Number(quantities[line.id]) > 0" :lots="allocations[line.id] ?? []" :expected="quantities[line.id]" :sku="line.sku" :material-name="line.material_name" :unit="line.unit" selectable optional :show-source="false" :disabled="detailDisabled" :options="(lots.lines.find(item => item.line_id === line.id)?.lots ?? []).map(lot => ({ value: lot.lot_id, label: `${lot.code} · 可用 ${lot.quantity}` }))" @add="addLot(line)" @remove="index => allocations[line.id].splice(index, 1)" />
          </div></template>
          <p v-if="usesLots" class="muted">已知多批次的部分交接请选实际批次；未指定时由服务端核对能否沿用完整来源，数量不足或来源不明确时不会自动完成。</p>
          <label>{{ operation === 'execute' ? '本次说明（可选）' : '操作原因' }}<AppInput v-model="operationReason" maxlength="200" :required="operation !== 'execute'" /></label>
          <div class="flow-actions"><AppButton :disabled="busy" @click="cancelOperation">收起</AppButton><AppButton variant="primary" :disabled="detailDisabled || operation === 'reverse' && (!approvalReady || app.documentApprovalRecord?.intent !== 'reverse' || app.documentApprovalRecord?.status !== 'approved')" @click="submitOperation">提交本次处理</AppButton></div>
        </section>
        <DocumentApprovalPanel v-if="approvalType" part="opinion" />
      </template>
      <template #footer><div class="flow-actions"><DocumentApprovalPanel v-if="approvalType" part="actions" />
        <template v-if="detail && !operation"><AppButton :disabled="detailDisabled" @click="refreshDetail">刷新</AppButton>
          <AppButton v-if="detail.kind === kind && detail.kind !== 'receipt' && detail.status === 'draft' && canCreate && !['submitted', 'approved', 'executed'].includes(detail.approval?.status ?? '')" :disabled="detailDisabled" @click="editDraft">编辑草稿</AppButton>
          <AppButton v-if="actionable && hasExecutableLines && approved && app.can(executePermission)" variant="primary" :disabled="detailDisabled" @click="prepare('execute')">{{ executionLabel }}</AppButton>
          <AppButton v-if="detail.kind === 'exchange' && approved && app.can('material_dispatch.create')" :disabled="detailDisabled" @click="createReplacement">生成补发单</AppButton>
          <AppButton v-if="detail.kind === 'receipt' && actionable && app.can('material_receipt.handover_return')" :disabled="detailDisabled" @click="prepare('handover')">未签收实物退回</AppButton>
          <AppButton v-if="actionable && detail.kind !== 'receipt' && app.can(`${materialFlowPermission[detail.kind]}.close`)" :disabled="detailDisabled" @click="prepare('close')">关闭余额</AppButton>
          <AppButton v-if="['partial', 'completed', 'closed'].includes(detail.status) && app.can(`${materialFlowPermission[detail.kind]}.reverse`)" :disabled="detailDisabled" @click="prepare('reverse')">审批更正</AppButton>
        </template><AppButton :disabled="busy" @click="closeDetail(false)">关闭</AppButton>
      </div></template>
    </WorkspaceDocumentDialog>
  </section>
</template>

<style scoped>
/* 四页保持同一宽窄屏与明暗主题结构，状态和进度始终独立于审批。 */
.material-flow-workspace small, .flow-material-line { display: block; margin-top: 5px; color: var(--workspace-field-muted); font-size: 12px; }
.flow-error { color: #b94438; }
.flow-history, .flow-operation { margin-top: 24px; padding: 18px; border: 1px solid var(--workspace-field-border); border-radius: 12px; background: var(--workspace-field-background); }
.flow-history > div { display: flex; flex-direction: column; gap: 6px; padding: 12px 0; border-bottom: 1px solid var(--workspace-field-border); font-size: 13px; }
.flow-execute-line { display: flex; flex-direction: column; gap: 18px; margin: 18px 0; padding-bottom: 18px; border-bottom: 1px solid var(--workspace-field-border); }
.flow-execute-line > label { max-width: 460px; }
.flow-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; width: 100%; margin-top: 12px; }
:root[data-theme='dark'] .flow-error { color: #ffaaa2; }
</style>
