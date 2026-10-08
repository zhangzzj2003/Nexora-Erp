<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import AppStatusTag, { type AppStatusTone } from '../../../components/app/AppStatusTag.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { computed, nextTick, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 标题概览复用公共组件，业务状态分组仍由本页定义。
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import type { WorkspaceSummaryFilterOption } from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import { otherInboundGroup, otherInboundSummary, type OtherInboundFilter } from './other-inbound-summary'
import { useLocalPagination } from '../../../composables/use-local-pagination'
// 全部批次单据共享标题、固定操作区与数量核对表。
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import { appendDocumentMaterialRow, documentMaterialDisabled, documentMaterialIssue, documentMaterialLimit } from '../../../utils/document-material-lines'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import type {InboundLotLineInput} from '../../../../../shared/receipt-lot-api'
import type {OtherInbound} from '../../../../../shared/erp-api'
import OtherInboundActions from './OtherInboundActions.vue'
import { otherInboundActions, type OtherInboundAction } from './other-inbound-actions'
import { shortLocalTime } from '../../../utils/formatters'
import type { WorkspaceTableColumn } from '../../../utils/table-columns'
import { useOtherInboundMaterialDetails } from './other-inbound-material-details'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, materials, warehouses, otherInbounds, otherInboundForm, otherInboundReopenForms,
  otherInboundReversalReasons } = storeToRefs(store)
const { can, localTime, createOtherInbound, postOtherInbound, cancelOtherInbound,
  reverseOtherInbound } = store
const showForm = ref(false)
const pendingActionId = ref(0)
const reopenSourceId = ref(0)
// 编辑器复用同一套字段，普通新建与不同原单的重开草稿各自独立。
const editorForm = computed(() => reopenSourceId.value
  ? otherInboundReopenForms.value[reopenSourceId.value] ?? otherInboundForm.value : otherInboundForm.value)
// 会话清理或保存成功移除草稿后关闭编辑器，防止回落到普通草稿继续编辑。
watch(() => reopenSourceId.value && !otherInboundReopenForms.value[reopenSourceId.value], missing => {
  if (missing) { showForm.value = false; reopenSourceId.value = 0 }
}, { flush: 'sync' })
const reopenSource = computed(() => otherInbounds.value.find(item => item.id === reopenSourceId.value))
function startCreate(): void {
  reopenSourceId.value = 0
  showForm.value = true
}
const inboundPermissions = computed(() => ({
  create: can('other_inbound.create'), post: can('other_inbound.post'), cancel: can('other_inbound.cancel'), reverse: can('other_inbound.reverse')
}))
// 点击时重新按 ID 找当前快照；列表和详情走同一入口，刷新后不执行旧状态的动作。
async function handleInboundAction(identifier: number, action: OtherInboundAction): Promise<void> {
  if (busy.value || connectionLost.value || pendingActionId.value) return
  const inbound = otherInbounds.value.find(item => item.id === identifier)
  if (!inbound || !otherInboundActions(inbound, inboundPermissions.value).some(item => item.key === action)) return
  pendingActionId.value = identifier
  try {
    if (action === 'approval' || action === 'reversalApproval') {
      await store.openDocumentApproval({ document_type: 'WarehouseInbound', document_id: identifier,
        intent: action === 'approval' ? 'execute' : 'reverse' })
    } else if (action === 'post') await postOtherInbound(identifier)
    else if (action === 'cancel') await cancelOtherInbound(identifier)
    else if (action === 'lots') startLotPost(inbound)
    else if (action === 'reopen') {
      if (!store.prepareOtherInboundReopen(identifier)) return
      reopenSourceId.value = identifier
      detailInboundId.value = 0
      showForm.value = true
    }
    else await reverseApproved(identifier)
  } finally {
    // 保存失败仍保留详情与原草稿，允许用户读取原因后重试。
    pendingActionId.value = 0
  }
}
const { activeLine, showLine, setCompact } = useOtherInboundMaterialDetails(() => editorForm.value.lines)
// 表格行直接引用 Pinia 草稿，资料刷新及删行后仍按该行的真实对象修改数量。
const materialRows = computed(() => editorForm.value.lines.map((line, index) => ({
  line, index, material: materials.value.find(item => item.id === line.material_id)
})))
const materialColumns: readonly WorkspaceTableColumn[] = [
  { key: 'sku', title: '物料编码', width: '170' },
  { key: 'name', title: '物料 / 资料', width: '470' },
  // 新建与重开共用此明细表，单位的表头和内容保持居中。
  { key: 'unit', title: '单位', width: '70', align: 'center' },
  { key: 'quantity', title: '数量', width: '130' },
  { key: 'actions', title: '操作', width: '80' }
]
const materialIssue = computed(() => documentMaterialIssue(editorForm.value.lines, materials.value))
const addDisabled = computed(() => editorForm.value.lines.length >= documentMaterialLimit
  || !materials.value.some(item => !editorForm.value.lines.some(line => line.material_id === item.id)))
const pendingFocus = ref<(typeof editorForm.value.lines)[number] | null>(null)
function materialOptions(index: number) {
  return materials.value.map(item => ({label: `${item.sku} · ${item.name}`, value: item.id,
    disabled: documentMaterialDisabled(editorForm.value.lines, index, item.id)}))
}
function addMaterialRow(): void {
  if (busy.value || connectionLost.value || addDisabled.value) return
  editorForm.value.lines = appendDocumentMaterialRow(editorForm.value.lines)
  pendingFocus.value = editorForm.value.lines.at(-1) ?? null
  // 新增时把资料展示切换到新行，之前的行自动保留简短摘要。
  if (pendingFocus.value) showLine(pendingFocus.value)
}
function focusNewRow(line: (typeof editorForm.value.lines)[number], instance: Element | ComponentPublicInstance | null): void {
  // vxe 可能延迟挂载新行，等选择器的真实引用出现后再聚焦，不依赖固定延时。
  if (instance && pendingFocus.value === line && 'focus' in instance && typeof instance.focus === 'function') {
    const focus = instance.focus as () => void
    pendingFocus.value = null
    void nextTick(() => { if (!busy.value && !connectionLost.value) focus() })
  }
}
const activeInboundId = ref(0)
const lotDrafts = ref<InboundLotLineInput[]>([])
const activeInbound = computed(() => otherInbounds.value.find(item =>
  item.id === activeInboundId.value && item.status === 'draft' && item.approval?.status === 'approved') ?? null)
const query = ref('')
const statusFilter = ref<OtherInboundFilter>('all')
const searched = computed(() => otherInbounds.value.filter((item) =>
  [documentSearch(item), item.id, item.reference, item.warehouse_name, item.note, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
// 概览不受搜索或分页影响；列表按所选分类和关键词取交集。
const summary = computed(() => otherInboundSummary(otherInbounds.value))
const summaryOptions = computed<WorkspaceSummaryFilterOption<OtherInboundFilter>[]>(() => [
  { key: 'all', label: '全部单据', count: summary.value.all, hint: '全部可见入库单据；点击清除状态筛选' },
  { key: 'pending', label: '未处理', count: summary.value.pending, hint: '尚未完成入库，包含待送审、审批中、已批准、已驳回和已撤回', tone: 'pending' },
  { key: 'processed', label: '已处理', count: summary.value.processed, hint: '已确认入库且未冲销', tone: 'success' },
  { key: 'cancelled', label: '已取消', count: summary.value.cancelled, hint: '已取消的入库单据', tone: 'neutral' },
  { key: 'reversed', label: '已冲销', count: summary.value.reversed, hint: '已入库后完成冲销的单据', tone: 'reversed' }
])
const filtered = computed(() => searched.value.filter(item => statusFilter.value === 'all' || otherInboundGroup(item) === statusFilter.value))
// 关键词和状态共同决定分页身份，任一筛选变化均回到首页。
const paginationFilter = computed(() => JSON.stringify([query.value, statusFilter.value]))
// 仅对筛选后的展示数据分页，完整入库快照和详情、重开草稿保持独立。
const { rows, total, page, pageSize, changePage } = useLocalPagination(filtered, paginationFilter)
// 列表保持两行摘要，批次证据放入悬停说明，完整物料与批次仍由详情展示。
function materialPreviewTitle(inbound: OtherInbound, line: OtherInbound['lines'][number]): string {
  const summary = `${line.material_name} × ${line.quantity} ${line.unit}`
  if (inbound.status !== 'posted') return summary
  const proof = line.physical_lots?.length
    ? `实物批次：${line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；来源批号 ${lot.supplier_lot || '未提供'}）`).join('、')}`
    : '普通入库，未登记实物批次。'
  return `${summary}\n${proof}`
}
const reasonName = { opening: '期初补录', gift: '赠品', other: '其他' }
// 详情按 ID 读取当前快照，与新建草稿、批次登记各自独立；刷新后不展示过期对象。
const detailInboundId = ref(0)
const detailInbound = computed(() => otherInbounds.value.find(item => item.id === detailInboundId.value) ?? null)
const detailColumns = [
  { key: 'sku', title: '物料编码', width: '180' },
  { key: 'name', title: '物料名称', width: '240' },
  { key: 'quantity', title: '数量', width: '110' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'lots', title: '实物批次', width: '340' }
]
function inboundStatus(inbound: OtherInbound): string {
  return inbound.status === 'draft' ? ({ draft: '待送审', submitted: '审批中', approved: '已批准，待入库',
    rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }[inbound.approval?.status ?? 'draft']) : inbound.status === 'cancelled' ? '已取消'
    : inbound.reversal_id ? '已冲销' : '已入库'
}
function inboundStatusTone(inbound: OtherInbound): AppStatusTone {
  // 先判断仓库终态，避免已取消或已冲销的单据仍沿用旧审批记录的成功颜色。
  if (inbound.status === 'cancelled') return 'neutral'
  if (inbound.status === 'posted') return inbound.reversal_id ? 'reversed' : 'success'
  return ({ draft: 'pending', submitted: 'info', approved: 'ready', rejected: 'danger',
    withdrawn: 'neutral', executed: 'success' } as const)[inbound.approval?.status ?? 'draft']
}
const columns: readonly WorkspaceTableColumn[] = [
  // 单号与审计信息分列，列宽保证长单号和时间完整展示，窄窗口沿用公共表格横向滚动。
  { key: 'document', title: '单据号', width: '230' },
  // 短信息列与操作列统一居中，长文本列继续左对齐以便阅读。
  { key: 'status', title: '状态', width: '160', align: 'center' },
  { key: 'operator', title: '处理人', width: '110', align: 'center' },
  { key: 'source', title: '仓库与来源', width: '220' },
  { key: 'lines', title: '物料明细', width: '310' },
  // 时间紧邻操作并固定在右侧，横向查看物料时仍能对照创建时间。
  { key: 'time', title: '时间', width: '150', fixed: 'right', align: 'center' },
  { key: 'actions', title: '操作', width: '200', align: 'center' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  // 原生表单校验之外再检查物料和数量，防止空明细或已失效物料提交到服务端。
  if (connectionLost.value || !can('other_inbound.create') || materialIssue.value) return
  await submitCreateDialog(reopenSourceId.value
    ? () => store.createReopenedOtherInbound(reopenSourceId.value) : createOtherInbound, { busy, error, notice }, showForm)
}
function startLotPost(inbound: OtherInbound): void {
  // 批次登记是批准后的可选实物证据，不承担业务审批。
  if (inbound.approval?.status !== 'approved' || busy.value || connectionLost.value) return
  activeInboundId.value = inbound.id
  lotDrafts.value = inbound.lines.map(line => ({inbound_line_id: line.id,
    lots: [{quantity: line.quantity, supplier_lot: null, manufactured_on: null, expires_on: null}]}))
}
function addLot(line: InboundLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({quantity: '', supplier_lot: null,
    manufactured_on: null, expires_on: null})
}
const lotIssue = computed(() => {
  const inbound = activeInbound.value
  if (!inbound || lotDrafts.value.length !== inbound.lines.length) return '入库单明细已经变化，请重新读取。'
  for (const line of inbound.lines) {
    const draft = lotDrafts.value.find(item => item.inbound_line_id === line.id)
    if (!draft || !draft.lots.length || draft.lots.length > 20) return '每条入库明细至少登记一个实物批次。'
    const expected = receiptLotMilli(line.quantity)
    let total = 0n
    for (const part of draft.lots) {
      const value = receiptLotMilli(part.quantity)
      if (value === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      total += value
      if (part.supplier_lot && part.supplier_lot.length > 100) return '来源批号不能超过 100 字。'
      if (part.manufactured_on && !receiptLotDate(part.manufactured_on)) return '生产日期无效。'
      if (part.expires_on && !receiptLotDate(part.expires_on)) return '失效日期无效。'
      if (part.manufactured_on && part.expires_on && part.expires_on < part.manufactured_on)
        return '失效日期不能早于生产日期。'
    }
    if (expected === null || total !== expected) return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})
async function confirmLotPost(): Promise<void> {
  if (!activeInbound.value || lotIssue.value || busy.value || connectionLost.value) return
  await postOtherInbound(activeInbound.value.id, lotDrafts.value.map(line => ({
    inbound_line_id: line.inbound_line_id,
    lots: line.lots.map(part => ({quantity: part.quantity, supplier_lot: part.supplier_lot?.trim() || null,
      manufactured_on: part.manufactured_on, expires_on: part.expires_on}))})))
}
// 执行冲销前从服务端读取已批准原因；不能使用未送审的列表输入。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await store.openDocumentApproval({ document_type: 'WarehouseInbound', document_id: identifier, intent: 'reverse' })) return
  const record = store.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  otherInboundReversalReasons.value[identifier] = record.reversal_reason
  store.closeDocumentApproval()
  await reverseOtherInbound(identifier)
}
</script>

<template>
  <section class="stack">
    <!-- 延后解析外壳目标，直接复用本页筛选状态；切换路由不会留下旧统计。 -->
    <Teleport defer to="#workspace-page-summary">
      <WorkspaceSummaryFilters v-model="statusFilter" :options="summaryOptions" />
    </Teleport>
    <WorkspaceTable
      :show-title="false"
      :data="rows"
      :pagination="{ page, pageSize, total }"
      @page-change="changePage"
      title="其他入库"
      :columns="columns"
      :min-table-width="1410"
    >
      <template #actions>
        <AppButton
          v-if="can('other_inbound.create')"
          :disabled="busy || connectionLost"
          @click="startCreate"
          variant="primary"
          type="button"
          >新建其他入库</AppButton
        >
      </template>
      <template #filters>
        <label>搜索入库单<AppInput v-model="query" placeholder="单号、参考号、仓库或物料" /></label>
      </template>
      <template #beforeTable>
        <WorkspaceDocumentDialog
          v-if="can('other_inbound.create')"
          v-model:show="showForm"
          :title="reopenSourceId ? `重开为新单 · ${reopenSource ? documentLabel(reopenSource) : '原单'}` : '非采购来源入库'"
          :data="materialRows"
          :columns="materialColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!!materialIssue"
          :add-disabled="addDisabled"
          :min-table-width="960"
          :hint="reopenSourceId ? '保存后生成新单号并重新送审；原单保留已取消状态，原审批和批次记录不带入。' : '创建草稿后提交独立审批，批准并确认后才增加库存；这类入库不产生采购应付。'"
          @submit="submitCreate"
          @add-material="addMaterialRow"
        >
          <template #basicInfo>
            <label>仓库<WorkspaceSelect v-model="editorForm.warehouse_id" required
              :disabled="busy || connectionLost"
              :options="warehouses.map(item => ({ label: item.name, value: item.id }))" /></label>
            <label>用途<WorkspaceSelect v-model="editorForm.reason" required
              :disabled="busy || connectionLost"
              :options="[{ label: '期初补录', value: 'opening' }, { label: '赠品', value: 'gift' }, { label: '其他', value: 'other' }]" /></label>
            <label>参考号<AppInput v-model.trim="editorForm.reference" maxlength="100" :disabled="busy || connectionLost" /></label>
            <label>入库说明<AppInput v-model.trim="editorForm.note" required maxlength="200" :disabled="busy || connectionLost" /></label>
          </template>
          <template #materialPicker>
            <p v-if="materialRows.length && materialIssue" role="alert" class="inbound-material-issue">{{ materialIssue }}</p>
          </template>
          <template #cell-sku="{ row }"><strong>{{ row.material?.sku ?? '待选择' }}</strong></template>
          <template #cell-name="{ row }">
            <WorkspaceMaterialSelect :ref="instance => focusNewRow(row.line, instance)"
              v-model="row.line.material_id" :options="materialOptions(row.index)" :materials="materials" :categories="store.materialCategories" required
              :compact="activeLine !== row.line" @update:compact="value => setCompact(row.line, value)" @change="showLine(row.line)"
              :disabled="busy || connectionLost" :aria-label="`第 ${row.index + 1} 行物料`" />
          </template>
          <template #cell-unit="{ row }">{{ row.material?.unit ?? '—' }}</template>
          <template #cell-quantity="{ row }">
            <!-- 明细数量直接输入；隐藏步进按钮但仍沿用原来的数值边界。 -->
            <AppInput v-model.trim="row.line.quantity" type="number" hide-number-controls min="0.001"
              max="1000000" step="0.001" required :disabled="busy || connectionLost"
              :aria-label="`${row.material?.name ?? '物料'}数量`" />
          </template>
          <template #cell-actions="{ row }">
            <AppButton type="button" variant="text" :disabled="busy || connectionLost"
              :aria-label="`移除${row.material?.name ?? '物料'}`" @click="editorForm.lines.splice(row.index, 1)">移除</AppButton>
          </template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-document="{ row: item }">
        <!-- 单号直接打开只读详情；使用公共文本按钮保留键盘操作，断线仍可查看已加载快照。 -->
        <AppButton type="button" variant="text" :aria-label="`查看单据 ${documentLabel(item)} 详情`"
          @click="detailInboundId = item.id">{{ documentLabel(item) }}</AppButton>
      </template>
      <!-- 时间、处理人沿用原单据中的创建记录，避免改变历史字段含义。 -->
      <template #cell-time="{ row: item }">{{ shortLocalTime(item.created_at) }}</template>
      <template #cell-status="{ row: item }">
        <AppStatusTag :label="inboundStatus(item)" :tone="inboundStatusTone(item)" />
      </template>
      <template #cell-operator="{ row: item }">{{ item.created_by_name }}</template>
      <template #cell-source="{ row: item }">
        {{ item.warehouse_name }} · {{ reasonName[item.reason] }}
        <!-- 参考号只在详情显示，筛选继续使用完整记录中的参考号。 -->
        <small class="inbound-note" :title="item.note">{{ item.note }}</small>
      </template>
      <template #cell-lines="{ row: item }">
        <!-- 标签与整块摘要并排，使其相对两行物料垂直居中，不再附属于第二行。 -->
        <div class="inbound-material-summary">
          <ul class="inbound-material-preview">
            <li v-for="line in item.lines.slice(0, 2)" :key="line.id">
              <span class="inbound-material-text" :title="materialPreviewTitle(item, line)">{{ line.material_name }} × {{ line.quantity }} {{ line.unit }}</span>
            </li>
          </ul>
          <span v-if="item.lines.length > 2" class="inbound-material-more"
            :title="item.lines.slice(2).map(line => materialPreviewTitle(item, line)).join('\n')"
            :aria-label="`另有 ${item.lines.length - 2} 项物料`">+{{ item.lines.length - 2 }} 项</span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <OtherInboundActions compact :inbound="item" :permissions="inboundPermissions"
          :disabled="busy || connectionLost || !!pendingActionId" @action="action => handleInboundAction(item.id, action)" />
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small>
      </template>
      <template #empty>{{ query || statusFilter !== 'all' ? '没有匹配的入库单。' : '暂无其他入库单。' }}</template>
    </WorkspaceTable>
    <WorkspaceDocumentDialog v-if="detailInbound" :show="true" read-only
      :title="`其他入库详情 · ${documentLabel(detailInbound)}`"
      :data="detailInbound.lines" :columns="detailColumns" :min-table-width="940"
      hint="可在物料明细右侧处理当前单据；操作完成后自动更新状态。"
      :busy="pendingActionId === detailInbound.id"
      @update:show="value => { if (!value) detailInboundId = 0 }">
      <template #documentActions>
        <OtherInboundActions :inbound="detailInbound" :permissions="inboundPermissions"
          :disabled="busy || connectionLost || !!pendingActionId" @action="action => detailInbound && handleInboundAction(detailInbound.id, action)" />
      </template>
      <template #basicInfo>
        <div class="inbound-detail-field"><span>单号</span><strong>{{ documentLabel(detailInbound) }}</strong></div>
        <div class="inbound-detail-field"><span>状态</span><AppStatusTag :label="inboundStatus(detailInbound)" :tone="inboundStatusTone(detailInbound)" /></div>
        <div class="inbound-detail-field"><span>仓库</span><strong>{{ detailInbound.warehouse_name }}</strong></div>
        <div class="inbound-detail-field"><span>用途</span><strong>{{ reasonName[detailInbound.reason] }}</strong></div>
        <div class="inbound-detail-field"><span>参考号</span><strong>{{ detailInbound.reference || '—' }}</strong></div>
        <div class="inbound-detail-field"><span>入库说明</span><strong>{{ detailInbound.note || '—' }}</strong></div>
        <div class="inbound-detail-field"><span>创建人</span><strong>{{ detailInbound.created_by_name }}</strong></div>
        <div class="inbound-detail-field"><span>创建时间</span><strong>{{ localTime(detailInbound.created_at) }}</strong></div>
        <div v-if="detailInbound.posted_at" class="inbound-detail-field"><span>确认记录</span><strong>{{ localTime(detailInbound.posted_at) }} · {{ detailInbound.posted_by_name || '—' }}</strong></div>
        <div v-if="detailInbound.cancelled_at" class="inbound-detail-field"><span>取消时间</span><strong>{{ localTime(detailInbound.cancelled_at) }}</strong></div>
        <div v-if="detailInbound.reversal_id" class="inbound-detail-field"><span>冲销记录</span><strong>{{ detailInbound.reversed_at ? localTime(detailInbound.reversed_at) : '—' }} · {{ detailInbound.reversed_by_name || '—' }}</strong></div>
        <div v-if="detailInbound.reversal_id" class="inbound-detail-field"><span>冲销原因</span><strong>{{ detailInbound.reversal_reason || '—' }}</strong></div>
      </template>
      <template #cell-sku="{ row }"><strong>{{ row.sku }}</strong></template>
      <template #cell-name="{ row }">{{ row.material_name }}</template>
      <template #cell-quantity="{ row }">{{ row.quantity }}</template>
      <template #cell-unit="{ row }">{{ row.unit }}</template>
      <template #cell-lots="{ row }">
        <div v-for="lot in row.physical_lots" :key="lot.id" class="inbound-detail-lot">
          <strong>{{ lot.code }}</strong><small>{{ lot.quantity }} {{ row.unit }} · 来源批号 {{ lot.supplier_lot || '未提供' }}</small>
          <small v-if="lot.manufactured_on">生产日期：{{ lot.manufactured_on }}</small>
          <small v-if="lot.expires_on">失效日期：{{ lot.expires_on }}</small>
        </div>
        <span v-if="!row.physical_lots?.length">{{ detailInbound.status === 'posted' ? '普通入库，未登记实物批次。' : '尚未登记实物批次' }}</span>
      </template>
    </WorkspaceDocumentDialog>
    <DocumentApprovalDialog title="其他入库审批" />
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog v-if="activeInbound && can('other_inbound.post')" :show="true"
      title="其他入库 · 批次登记" :document-number="documentLabel(activeInbound)"
      hint="按实际入库逐行登记批次，数量之和须等于入库量。来源批号和日期缺失时留空，系统会保留独立的入库来源编号。"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="确认入库"
      @update:show="value => { if (!value) activeInboundId = 0 }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.inbound_line_id" :lots="line.lots"
        :sku="activeInbound.lines.find(item => item.id === line.inbound_line_id)?.sku" :material-name="activeInbound.lines.find(item => item.id === line.inbound_line_id)?.material_name"
        :unit="activeInbound.lines.find(item => item.id === line.inbound_line_id)?.unit" :expected="activeInbound.lines.find(item => item.id === line.inbound_line_id)?.quantity ?? ''"
        expected-label="应入库" quantity-label="批次数量"
        :disabled="busy || connectionLost" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)" />
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped>
/* 列表说明只占一行，完整内容保留在悬停提示和详情中，不截断原始数据。 */
.inbound-note { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 摘要按内容宽度排布，让余量标签紧跟两行明细；窄列仍可收缩并省略长文本。 */
.inbound-material-summary { display: flex; align-items: center; gap: 8px; min-width: 0; }
.inbound-material-preview { flex: 0 1 auto; min-width: 0; list-style: none; margin: 0; padding: 0; }
.inbound-material-preview li { display: flex; align-items: baseline; gap: 8px; min-width: 0; line-height: 1.7; }
.inbound-material-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.inbound-material-more { flex: none; padding: 0 6px; border-radius: 6px; background: color-mix(in srgb, var(--workspace-field-muted) 12%, transparent); color: var(--workspace-field-muted); white-space: nowrap; font-size: 12px; line-height: 20px; }
/* 详情展示历史单据字段，使用可选中复制的文本，并兼容长说明和窄窗口。 */
.inbound-detail-field { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.inbound-detail-field > span:first-child { color: var(--workspace-field-muted); font-size: 12px; }
.inbound-detail-field strong { font-weight: 500; overflow-wrap: anywhere; white-space: pre-wrap; }
.inbound-detail-lot + .inbound-detail-lot { margin-top: 12px; }
</style>

<style scoped>
/* 校验提示明确指向未完成的表格行，明暗主题保持可读。 */
.inbound-material-issue { margin: 10px 0 0; color: #c45a53; font-size: 13px; }
:root[data-theme='dark'] .inbound-material-issue { color: #ffaaa2; }
</style>
