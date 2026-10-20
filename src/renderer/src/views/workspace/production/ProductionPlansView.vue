<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppModal from '../../../components/app/AppModal.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import ProductionPlanEditor from './ProductionPlanEditor.vue'
import { documentLabel, documentSearch, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import type { ProductionPlan, ProductionPlanLine, ProductionPlanReleaseInput } from '../../../../../shared/production-plan-api'
import { productionPlanQuantity } from '../../../../../shared/production-plan-api'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import { canCancelPlan, canReleasePlan, planPriority, planProgress, planStatus, planStatusTone, planProgressTone } from './production-plan-display'
import { mrpSourceStatus } from './mrp-display'
import { routeByKey } from '../../../router/workspace-routes'

const store = usePiniaAppStore()
const router = useRouter()
const { productionPlans: records, productionPlanDetail: detail, productionPlanOptions: options,
  productionPlanError: error, productionPlanLoading: loading, productionPlanForm: form,
  productionPlanEdit: editing,
  busy, connectionLost, user, server, error: operationError } = storeToRefs(store)
const editor = ref(false), showDetail = ref(false), pending = ref(false), query = ref(''), filter = ref('all')
const command = ref<'release' | 'cancel' | null>(null)
const release = ref<ProductionPlanReleaseInput | null>(null)
const cancelTarget = ref<ProductionPlan | null>(null)
const reason = ref('')
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const permissions = computed(() => user.value?.permissions ?? [])
const counts = computed(() => [
  { key: 'all', label: '全部计划', count: records.value.length, hint: '包含草稿与历史记录' },
  { key: 'pending', label: '待审批', count: records.value.filter(row => row.status !== 'cancelled' && ['draft', 'submitted', 'rejected', 'withdrawn'].includes(row.approval.status)).length, hint: '尚未完成批准' },
  { key: 'active', label: '待完成', count: records.value.filter(row => row.status !== 'cancelled' && ['approved', 'executed'].includes(row.approval.status) && row.progress !== 'completed').length, hint: '已批准且尚未全部报工' },
  { key: 'overdue', label: '延期计划', count: records.value.filter(row => row.overdue_count > 0).length, hint: '已过计划完工日且报工未完成' },
  { key: 'completed', label: '报工完成', count: records.value.filter(row => row.progress === 'completed' && row.status !== 'cancelled').length, hint: '合格与不合格数量分别核对' },
])
const filtered = computed(() => records.value.filter(row => {
  const text = `${documentSearch(row)} ${row.reference} ${row.products} ${row.start_date} ${row.end_date}`.toLowerCase()
  if (!text.includes(query.value.trim().toLowerCase())) return false
  if (filter.value === 'overdue') return row.overdue_count > 0
  if (filter.value === 'completed') return row.status !== 'cancelled' && row.progress === 'completed'
  if (filter.value === 'pending') return row.status !== 'cancelled' && ['draft', 'submitted', 'rejected', 'withdrawn'].includes(row.approval.status)
  if (filter.value === 'active') return row.status !== 'cancelled' && ['approved', 'executed'].includes(row.approval.status) && row.progress !== 'completed'
  return true
}))
// 编号与名称各占一列，编号入口和操作列共用同一详情读取流程。
const columns = [{ key: 'plan', title: '计划编号', width: '230' }, { key: 'reference', title: '计划名称', width: '220' }, { key: 'products', title: '生产产品', width: '230' },
  { key: 'dates', title: '计划周期', width: '190' }, { key: 'status', title: '审批 / 执行', width: '180' },
  { key: 'actions', title: '操作', width: '230' }]
const lineColumns = [{ key: 'product', title: '产品 / 来源', width: '240' }, { key: 'dates', title: '排期 / 优先级', width: '190' },
  { key: 'quantity', title: '计划产量', width: '110' }, { key: 'release', title: '已下达 / 未下达', width: '160' },
  { key: 'progress', title: '报工 / 合格 / 不合格', width: '200' }, { key: 'actions', title: '操作', width: '140' }]
const releaseColumns = [{ key: 'work_order', title: '生产工单', width: '230' }, { key: 'quantity', title: '下达数量', width: '130' },
  { key: 'status', title: '工单状态', width: '140' }, { key: 'reason', title: '下达依据', width: '230' }, { key: 'created_at', title: '下达时间', width: '190' }]
const releaseProblem = computed(() => {
  if (!release.value) return ''
  try {
    productionPlanQuantity(release.value.quantity)
    const line = detail.value?.lines.find(row => row.id === release.value?.line_id)
    return !line || Number(release.value.quantity) > Number(line.unreleased_quantity) ? '下达数量不能超过未下达数量' : ''
  } catch (cause) { return cause instanceof Error ? cause.message : '请核对数量' }
})
const releaseLine = computed(() => detail.value?.lines.find(row => row.id === release.value?.line_id))
function newPlan(): void {
  if (disabled.value || !options.value || !store.can('production_plan.create')) return
  if (!form.value.lines.length) form.value.lines.push({ bom_id: 0, sales_order_line_id: null,
    warehouse_id: options.value.warehouses[0]?.id ?? 0, quantity: '1', start_date: options.value.today,
    end_date: options.value.today, priority: 'normal' })
  editor.value = true
}
async function openDetail(row: ProductionPlan): Promise<void> {
  // 编号和详情按钮都遵守当前连接、忙碌和查看权限约束。
  if (disabled.value || !store.can('production_plan.view')) return
  showDetail.value = true; pending.value = true
  try { await store.loadProductionPlanDetail(row.id) }
  finally { pending.value = false }
}
function closeDetail(): void { showDetail.value = false; pending.value = false; store.clearProductionPlanDetail() }
async function openWorkOrder(id: number): Promise<void> {
  if (disabled.value || !store.can('production.view')) return
  // 复用工单页已有的指定单据入口，按关联 ID 打开，避免再次按编号搜索。
  closeDetail(); store.closeDocumentApproval()
  await router.push({ path: routeByKey('workOrders').path, query: { document_id: id } })
}
function edit(): void {
  if (detail.value && store.editProductionPlan(detail.value)) { closeDetail(); editor.value = true }
}
function openRelease(line: ProductionPlanLine): void {
  if (disabled.value || !detail.value || !canReleasePlan(detail.value, line, permissions.value)) return
  release.value = { id: detail.value.id, version: detail.value.version, approval_version: detail.value.approval.version,
    line_id: line.id, quantity: line.unreleased_quantity, reason: '', request_id: crypto.randomUUID() }
  reason.value = ''; operationError.value = ''; command.value = 'release'
}
function openCancel(): void {
  if (!detail.value || !canCancelPlan(detail.value, permissions.value)) return
  cancelTarget.value = { ...detail.value }; reason.value = ''; operationError.value = ''; command.value = 'cancel'
}
async function execute(): Promise<void> {
  if (disabled.value || !reason.value.trim()) return
  if (command.value === 'release' && release.value) {
    const current = detail.value, request = release.value, line = current?.lines.find(row => row.id === request.line_id)
    // 弹窗固定计划、业务版本及审批版本；后台刷新或切换详情后必须重新打开。
    if (!current || !line || current.id !== request.id || current.version !== request.version
      || current.approval.version !== request.approval_version || !canReleasePlan(current, line, permissions.value)) {
      operationError.value = '计划或审批已变化，请关闭后重新打开下达窗口。'; return
    }
    if (!releaseProblem.value && await store.releaseProductionPlan({ ...request, reason: reason.value })) command.value = null
  } else if (command.value === 'cancel' && cancelTarget.value && detail.value) {
    if (detail.value.id !== cancelTarget.value.id || detail.value.version !== cancelTarget.value.version
      || !canCancelPlan(detail.value, permissions.value)) { operationError.value = '计划状态已变化，请重新读取。'; return }
    if (await store.cancelProductionPlan(cancelTarget.value, reason.value)) command.value = null
  }
}
async function refresh(): Promise<void> {
  const id = showDetail.value ? detail.value?.id : undefined
  if (await store.loadProductionPlans() && id && showDetail.value) await store.loadProductionPlanDetail(id)
}
function resetFilters(): void {
  // 列表重置只清除关键词和状态，不改动未保存的生产安排。
  query.value = ''; filter.value = 'all'
}
function resetDialogs(): void { editor.value = false; closeDetail(); command.value = null; release.value = null; reason.value = '' }
onMounted(() => store.loadProductionPlans())
onUnmounted(store.clearProductionPlanDetail)
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${permissions.value.join('|')}`, () => {
  resetDialogs(); if (store.can('production_plan.view')) void store.loadProductionPlans()
})
watch(connectionLost, lost => { resetDialogs(); if (!lost) void store.loadProductionPlans() })
</script>
<template>
  <section class="stack production-plans">
    <!-- 与其他入库共用标题右侧统计目标，页面卸载时自动移除本页概览。 -->
    <Teleport defer to="#workspace-page-summary">
      <WorkspaceSummaryFilters v-model="filter" :options="counts" />
    </Teleport>
    <p v-if="options?.unavailable_boms?.length" role="status">{{ options.unavailable_boms.length }} 个 BOM 的下层配方暂不可用，已从新计划候选中移除，请在产品与 BOM 中核对。已有计划仍可查看与处理。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <WorkspaceTable title="生产计划" :show-title="false" :columns="columns" :data="filtered" :loading="loading" :min-table-width="1280">
      <!-- 功能按钮统一进入表格筛选栏右侧，主操作放在末尾，窄窗口沿用公共换行布局。 -->
      <template #actions>
        <AppButton :disabled="disabled" @click="refresh">{{ loading ? '正在读取…' : '刷新计划' }}</AppButton>
        <AppButton v-if="store.can('mrp.view')" @click="store.navigateToRoute('materialPlanning')">物料需求计划</AppButton>
        <AppButton v-if="store.can('production.view')" @click="store.navigateToRoute('workOrders')">生产工单</AppButton>
        <AppButton v-if="store.can('production_plan.create') && form.lines.length" :disabled="disabled" @click="store.resetProductionPlanForm">清空未保存输入</AppButton>
        <AppButton v-if="store.can('production_plan.create')" variant="primary" :disabled="disabled || !options" @click.capture="captureDialogOrigin('production-plan-editor', $event)" @click="newPlan">{{ editing ? '继续编辑草稿' : form.lines.length ? '继续编制计划' : '新建生产计划' }}</AppButton>
      </template>
      <template #filters>
        <WorkspaceSearchFilters v-model:query="query" :filters="{}" search-label="搜索计划"
          search-placeholder="计划编号、名称、产品或日期" :reset-disabled="!query && filter === 'all'" @reset="resetFilters" />
      </template>
      <template #cell-plan="{ row }">
        <AppButton type="button" variant="text" :disabled="disabled" :aria-label="`查看生产计划 ${documentLabel(row)} 详情`"
          @click.capture="captureDialogOrigin('production-plan-detail', $event)" @click="openDetail(row)">{{ documentLabel(row) }}</AppButton>
      </template>
      <template #cell-reference="{ row }">{{ row.reference }}</template>
      <template #cell-products="{ row }">{{ row.products }}<span class="plan-line muted">{{ row.line_count }} 项生产安排</span></template>
      <template #cell-dates="{ row }">{{ row.start_date }}<span class="plan-line">至 {{ row.end_date }}</span><span v-if="row.overdue_count" class="plan-overdue">{{ row.overdue_count }} 项延期</span></template>
      <!-- 与其他入库复用圆点胶囊标签；取消优先，避免显示历史执行进度造成误解。 -->
      <template #cell-status="{ row }"><div class="plan-status-tags">
        <AppStatusTag :label="planStatus(row)" :tone="planStatusTone(row)" :aria-label="`审批状态：${planStatus(row)}`" />
        <AppStatusTag v-if="row.status !== 'cancelled'" :label="planProgress[row.progress]" :tone="planProgressTone[row.progress]" :aria-label="`执行状态：${planProgress[row.progress]}`" />
      </div></template>
      <template #cell-actions="{ row }"><div class="plan-toolbar">
        <AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('production-plan-detail', $event)" @click="openDetail(row)">计划详情</AppButton>
        <AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('document-approval', $event)" @click="store.openDocumentApproval({ document_type: 'ProductionPlan', document_id: row.id, intent: 'execute' })">单据审批</AppButton>
      </div></template>
      <template #empty>{{ query || filter !== 'all' ? '没有匹配的生产计划。' : '尚无生产计划。新建计划，安排产品、产量及开完工日期。' }}</template>
    </WorkspaceTable>
    <ProductionPlanEditor v-model:show="editor" @saved="showDetail = true" />
    <WorkspaceDocumentDialog :show="showDetail" :ready="!pending && !!detail" :load-error="error" origin-key="production-plan-detail"
      :title="detail ? `生产计划 · ${documentLabel(detail)}` : '生产计划详情'" :data="detail?.lines ?? []" :columns="lineColumns" :min-table-width="1110"
      read-only :show-add="false" :busy="busy" lines-title="产品排期与进度" @update:show="value => { if (!value) closeDetail() }" @invalidated="closeDetail">
      <template #basicInfo>
        <template v-if="detail"><div class="document-detail-field"><span>计划名称</span><strong>{{ detail.reference }}</strong></div>
          <div class="document-detail-field"><span>审批 / 执行</span><div class="plan-status-tags">
            <AppStatusTag :label="planStatus(detail)" :tone="planStatusTone(detail)" />
            <AppStatusTag v-if="detail.status !== 'cancelled'" :label="planProgress[detail.progress]" :tone="planProgressTone[detail.progress]" />
          </div></div>
          <div class="document-detail-field"><span>编制依据</span><strong>{{ detail.reason }}</strong></div>
          <div class="document-detail-field"><span>备注</span><strong>{{ detail.note || '—' }}</strong></div></template>
      </template>
      <template #documentActions><template v-if="detail">
        <AppButton v-if="detail.can_edit && store.can('production_plan.create')" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('production-plan-editor', $event)" @click="edit">编辑草稿</AppButton>
        <AppButton v-if="canCancelPlan(detail, permissions)" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('production-plan-command', $event)" @click="openCancel">取消计划</AppButton>
      </template></template>
      <template #cell-product="{ row }"><strong>{{ row.sku }} · {{ row.name }}</strong><span class="plan-line muted">BOM V{{ row.bom_version }} · {{ row.warehouse_name }}</span><span class="plan-line muted">{{ row.sales_order_id ? `销售来源 ${relatedDocumentLabel(row, 'sales_order')}` : '自主备货 / 手工计划' }}</span></template>
      <template #cell-dates="{ row }">{{ row.start_date }}<span class="plan-line">至 {{ row.end_date }} · {{ planPriority[row.priority] }}</span><span v-if="row.overdue" class="plan-overdue">已延期</span></template>
      <template #cell-quantity="{ row }">{{ row.quantity }} {{ row.unit }}</template>
      <template #cell-release="{ row }">{{ row.released_quantity }} / {{ row.unreleased_quantity }}<span v-if="detail?.status === 'cancelled' && Number(row.unreleased_quantity) > 0" class="plan-line muted">未下达部分已终止</span></template>
      <template #cell-progress="{ row }">{{ row.reported_quantity }} / {{ row.accepted_quantity }} / {{ row.rejected_quantity }}<span class="plan-line muted">未报工 {{ row.remaining_quantity }} {{ row.unit }}</span></template>
      <template #cell-actions="{ row }"><AppButton v-if="detail && canReleasePlan(detail, row, permissions)" size="small" :disabled="disabled" @click.capture="captureDialogOrigin('production-plan-command', $event)" @click="openRelease(row)">分批下达</AppButton><span v-else class="muted">—</span></template>
      <template #afterLines><template v-if="detail">
        <p class="muted">批准后，未下达计划和已生成工单分别参与物料需求计算。报工完成包含不合格数量，合格入库另列核对。</p>
        <WorkspaceTable title="下达记录" :columns="releaseColumns" :data="detail.releases" :min-table-width="920">
          <template #cell-work_order="{ row }"><AppButton v-if="store.can('production.view')" variant="text" size="small" :disabled="disabled" @click="openWorkOrder(row.work_order_id)">{{ relatedDocumentLabel(row, 'work_order') }}</AppButton><span v-else>{{ relatedDocumentLabel(row, 'work_order') }}</span></template>
          <template #cell-status="{ row }">{{ mrpSourceStatus(row.work_order_status) }}</template>
          <template #cell-created_at="{ row }">{{ store.localTime(row.created_at) }}</template>
          <template #empty>尚未下达工单。计划批准后可按产品分批下达。</template>
        </WorkspaceTable>
        <WorkspaceTable title="编制与变更记录" :columns="[{ key: 'action', title: '操作', width: '100' }, { key: 'reason', title: '依据' }, { key: 'changed_by', title: '操作人编号', width: '130' }, { key: 'created_at', title: '时间', width: '190' }]" :data="detail.changes" :min-table-width="650">
          <template #cell-action="{ row }">{{ ({ create: '新建', edit: '修改', release: '下达', cancel: '取消' } as Record<string, string>)[row.action] ?? row.action }}</template>
          <template #cell-created_at="{ row }">{{ store.localTime(row.created_at) }}</template>
        </WorkspaceTable>
      </template></template>
    </WorkspaceDocumentDialog>
    <DocumentApprovalDialog origin-key="document-approval" />
    <AppModal :show="!!command" origin-key="production-plan-command" :title="command === 'release' ? '分批下达生产计划' : '取消生产计划'" preset="card" :busy="busy"
      :style="{ width: 'min(560px, calc(100vw - 32px))' }" :mask-closable="!busy" :closable="!busy" @update:show="value => { if (!value) command = null }" @invalidated="command = null">
      <form class="stack" @submit.prevent="execute">
        <p>{{ detail?.reference }}<span v-if="command === 'release'"> · 生成生产工单草稿后，继续在工单中审批、下达及领料。</span></p>
        <p v-if="command === 'release' && releaseLine">{{ releaseLine.sku }} · {{ releaseLine.name }} · 未下达 {{ releaseLine.unreleased_quantity }} {{ releaseLine.unit }}</p>
        <p v-if="command === 'cancel'">取消后停止未下达安排，并从物料需求计划中移除这部分预计供需；已生成工单继续保留并独立执行。</p>
        <label v-if="command === 'release' && release">本批下达数量<AppInput v-model="release.quantity" type="number" hide-number-controls min="0.001" step="0.001" max="1000000" required :disabled="busy" /></label>
        <label>操作依据<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy" /></label>
        <p v-if="command === 'release' && releaseProblem" role="status">{{ releaseProblem }}</p><p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim() || command === 'release' && !!releaseProblem">{{ command === 'release' ? '生成工单草稿' : '确认取消' }}</AppButton>
      </form>
    </AppModal>
  </section>
</template>
<style scoped>
/* 复用工作台色彩与公共表格，长单据由公共详情窗口负责滚动和分页。 */
/* 两类状态保持同列分行展示，共用公共标签的明暗主题。 */
.plan-status-tags { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.plan-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.plan-line { display: block; margin-top: 5px; font-size: 12px; }
.plan-overdue { display: block; margin-top: 5px; color: var(--danger, #bd414a); font-size: 12px; }
</style>
