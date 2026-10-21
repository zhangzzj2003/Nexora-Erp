<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCheckbox } from 'naive-ui'
import AppModal from '../../../components/app/AppModal.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { documentLabel } from '../../../../../shared/document-numbering'
import { productionPlanQuantity } from '../../../../../shared/production-plan-api'
import type { ProductionPlanReleaseInput } from '../../../../../shared/production-plan-api'
import { groupProductionDemands } from './production-demand-groups'
import type { ProductionDemandSource } from './production-demand-groups'
import { planPriority, planPriorityTone, canReleasePlan } from './production-plan-display'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean]; viewPlan: [id: number] }>()
const store = usePiniaAppStore()
const { productionPlanDemands: plans, productionPlanDemandLoading: loading, productionPlanDemandError: error,
  productionPlanDemandReady: ready, busy, connectionLost, user, server, error: operationError } = storeToRefs(store)
const groups = computed(() => groupProductionDemands(plans.value))
const selected = ref<ProductionDemandSource | null>(null)
const request = ref<ProductionPlanReleaseInput | null>(null)
const checked = ref(false)
const selectionForm = ref<HTMLFormElement | null>(null)
const disabled = computed(() => busy.value || loading.value || connectionLost.value || !ready.value)
const columns = [{ key: 'plan', title: '来源计划', width: '240' }, { key: 'sales', title: '销售来源', width: '210' },
  { key: 'dates', title: '排期', width: '190' }, { key: 'priority', title: '优先级', width: '100' },
  { key: 'quantity', title: '待生成数量', width: '130' }, { key: 'actions', title: '操作', width: '130' }]
const problem = computed(() => {
  if (!request.value || !selected.value) return ''
  try { productionPlanQuantity(request.value.quantity) } catch (cause) { return cause instanceof Error ? cause.message : '请核对数量' }
  return Number(request.value.quantity) > Number(selected.value.line.unreleased_quantity) ? '本批数量不能超过该来源未生成数量' : ''
})
function reset(): void { selected.value = null; request.value = null; checked.value = false }
async function select(source: ProductionDemandSource): Promise<void> {
  if (disabled.value || !canReleasePlan(source.plan, source.line, user.value?.permissions ?? [])) return
  // 固定所选来源及版本；汇总展示不会把多个客户或计划的额度混成一个工单。
  selected.value = source; checked.value = false; operationError.value = ''
  request.value = { id: source.plan.id, version: source.plan.version, approval_version: source.plan.approval.version,
    line_id: source.line.id, quantity: source.line.unreleased_quantity, reason: '', request_id: crypto.randomUUID() }
  await nextTick()
  selectionForm.value?.scrollIntoView({ block: 'nearest' })
}
async function generate(): Promise<void> {
  if (disabled.value || !request.value || !selected.value || !checked.value || problem.value || !request.value.reason.trim()) return
  // 后台刷新改变计划版本后必须重选，不能沿用旧数量和旧定制依据。
  const current = plans.value.find(plan => plan.id === request.value?.id)
  if (!current || current.version !== request.value.version || current.approval.version !== request.value.approval_version) {
    operationError.value = '计划已变化，请刷新后重新选择生成。'; return
  }
  if (!canReleasePlan(selected.value.plan, selected.value.line, user.value?.permissions ?? [])) return
  if (await store.releaseProductionPlan({ ...request.value })) {
    // 写成功即清除可提交表单，随后刷新失败也不会引导重复建单。
    reset(); await store.loadProductionPlanDemands()
  }
}
async function refresh(): Promise<void> { reset(); await store.loadProductionPlanDemands() }
watch(() => props.show, () => reset())
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.permissions.join('|')}:${connectionLost.value}`, () => {
  reset(); emit('update:show', false)
})
</script>
<template>
  <AppModal :show="show" title="从生产计划生成工单" origin-key="production-demands" preset="card" :busy="busy"
    :style="{ width: 'min(1320px, calc(100vw - 32px))' }" :mask-closable="!busy" :closable="!busy"
    @update:show="emit('update:show', $event)" @invalidated="emit('update:show', false)">
    <div class="stack demand-body">
      <p class="muted">{{ ready ? `共 ${groups.length} 种机型待生成工单。` : '待生产数量待核对。' }}按型号汇总、按生产要求区分；生成时保留各计划来源，工单仍需独立审批。</p>
      <p v-if="error" role="alert">待生产需求读取失败：{{ error }}。请刷新后继续。</p>
      <p v-else-if="loading" role="status">正在核对待生产需求…</p>
      <p v-else-if="ready && !groups.length" role="status">暂无已批准且尚未生成工单的生产安排。</p>
      <section v-for="group in groups" :key="group.key" class="stack demand-model">
        <div class="demand-heading"><strong>{{ group.sku }} · {{ group.name }}</strong><strong>待生成 {{ group.quantity }} {{ group.unit }}</strong></div>
        <AppStatusTag v-if="group.variants.length > 1" tone="pending" label="同型号存在不同要求、BOM、仓库或未明确要求，请分组核对" />
        <section v-for="variant in group.variants" :key="variant.key" class="stack demand-variant">
          <div class="demand-heading"><strong class="demand-requirements">生产要求：{{ variant.requirements || '未填写，需核对 Logo、颜色、包装等要求' }}</strong><span>{{ variant.quantity }} {{ group.unit }}</span></div>
          <p class="muted">BOM V{{ variant.sources[0]?.line.bom_version }} · {{ variant.sources[0]?.line.warehouse_name }} · {{ variant.sources.length }} 条来源</p>
          <WorkspaceTable :show-title="false" title="计划来源" :data="variant.sources" :columns="columns" :min-table-width="1000">
            <template #cell-plan="{ row }"><AppButton variant="text" :disabled="busy || connectionLost" @click="emit('viewPlan', row.plan.id)">{{ documentLabel(row.plan) }}</AppButton><p class="muted">{{ row.plan.reference }}</p></template>
            <template #cell-sales="{ row }">{{ row.line.sales_order_document_no || (row.line.sales_order_id ? '#' + row.line.sales_order_id : '自主备货 / 手工计划') }}<p class="muted">{{ row.line.sales_reference }}</p></template>
            <template #cell-dates="{ row }">{{ row.line.start_date }}<br />至 {{ row.line.end_date }}</template>
            <template #cell-priority="{ row }"><AppStatusTag :label="planPriority[row.line.priority]" :tone="planPriorityTone[row.line.priority]" /></template>
            <template #cell-quantity="{ row }">{{ row.line.unreleased_quantity }} {{ row.line.unit }}</template>
            <template #cell-actions="{ row }"><AppButton v-if="canReleasePlan(row.plan, row.line, user?.permissions ?? [])" size="small" :disabled="disabled" @click="select(row)">选择生成</AppButton><span v-else class="muted">无生成权限</span></template>
          </WorkspaceTable>
        </section>
      </section>
      <form ref="selectionForm" v-if="selected && request" class="stack demand-selection" @submit.prevent="generate">
        <strong>本批来源：{{ documentLabel(selected.plan) }} · {{ selected.line.sku }} · {{ selected.line.name }}</strong>
        <p class="demand-requirements">生产要求：{{ selected.line.production_requirements || '未填写，请先与计划编制人员核对；需补充的要求应重新编制并审批。' }}</p>
        <label>本批生成数量（{{ selected.line.unit }}）<AppInput v-model="request.quantity" type="number" min="0.001" :max="selected.line.unreleased_quantity" step="0.001" hide-number-controls :disabled="disabled" required /></label>
        <label>生成依据<AppInput v-model.trim="request.reason" maxlength="500" :disabled="disabled" required /></label>
        <NCheckbox v-model:checked="checked" :disabled="disabled">已核对该来源的 Logo、颜色、包装等生产要求和本批数量</NCheckbox>
        <p v-if="problem" role="status">{{ problem }}</p><p v-if="operationError" role="alert">{{ operationError }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || !checked || !!problem || !request.reason.trim()">生成工单草稿</AppButton>
      </form>
    </div>
    <template #footer><div class="demand-footer"><AppButton :disabled="busy || loading || connectionLost" @click="refresh">刷新需求</AppButton><AppButton :disabled="busy" @click="emit('update:show', false)">关闭</AppButton></div></template>
  </AppModal>
</template>
<style scoped>
/* 长要求允许换行；弹窗内滚动，底部刷新与关闭保持可达。 */
.demand-body { max-height: 70vh; overflow-y: auto; }
.demand-model, .demand-selection { padding: 16px; border: 1px solid var(--workspace-field-border); border-radius: 12px; }
.demand-variant { gap: 8px; }
.demand-heading, .demand-footer { display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }
.demand-footer { justify-content: flex-end; }
.demand-requirements { white-space: pre-wrap; overflow-wrap: anywhere; }
/* 提醒标签不拉伸成整行，沿用其他页面的紧凑状态外观。 */
.demand-model > .app-status-tag { justify-self: start; max-width: 100%; white-space: normal; }
</style>
