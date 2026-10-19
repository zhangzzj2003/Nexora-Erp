<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import MrpDate from './MrpDate.vue'
import { productionPlanBody } from '../../../../../shared/production-plan-api'
import type { ProductionPlanLineInput } from '../../../../../shared/production-plan-api'
import { planPriority } from './production-plan-display'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean]; saved: [] }>()
const store = usePiniaAppStore()
const { productionPlanForm: form, productionPlanOptions: options, productionPlanEdit: edit,
  productionPlanError: error, busy, connectionLost } = storeToRefs(store)
const disabled = computed(() => busy.value || connectionLost.value || !store.can('production_plan.create'))
const columns = [{ key: 'product', title: '生产产品 / BOM', width: '280' }, { key: 'sales', title: '销售来源', width: '220' },
  { key: 'quantity', title: '计划产量', width: '150' }, { key: 'dates', title: '计划开工 / 完工', width: '200' },
  { key: 'warehouse', title: '完工仓库', width: '160' }, { key: 'priority', title: '优先级', width: '130' }, { key: 'actions', title: '操作', width: '80' }]
const priorities = Object.entries(planPriority).map(([value, label]) => ({ value, label }))
const problem = computed(() => {
  try { productionPlanBody(form.value); return '' } catch (cause) { return cause instanceof Error ? cause.message : '请补全计划' }
})
function addLine(): void {
  if (disabled.value || !options.value || form.value.lines.length >= 100) return
  form.value.lines.push({ bom_id: 0, sales_order_line_id: null, warehouse_id: options.value.warehouses[0]?.id ?? 0,
    quantity: '1', start_date: options.value.today, end_date: options.value.today, priority: 'normal' })
}
const materialId = (line: ProductionPlanLineInput) => options.value?.boms.find(bom => bom.id === line.bom_id)?.material_id ?? 0
function selectProduct(line: ProductionPlanLineInput, id: number): void {
  line.bom_id = options.value?.boms.find(bom => bom.material_id === id)?.id ?? 0
  line.sales_order_line_id = null
}
function salesOptions(line: ProductionPlanLineInput) {
  return [{ value: null as number | null, label: '自主备货 / 手工计划' }, ...(options.value?.sales_lines ?? [])
    .filter(sale => sale.material_id === materialId(line) && (Number(sale.available_quantity) > 0 || sale.id === line.sales_order_line_id))
    .map(sale => ({ value: sale.id, label: `${sale.sales_order_document_no || '#' + sale.sales_order_id} · ${sale.reference || '销售订单'} · 可安排 ${sale.available_quantity}` }))]
}
async function save(): Promise<void> {
  if (!disabled.value && props.show && !problem.value && await store.saveProductionPlan()) { emit('update:show', false); emit('saved') }
}
</script>
<template>
  <!-- 计划正文复用公共单据外壳；关闭只收起，同账号未保存输入仍保留。 -->
  <WorkspaceDocumentDialog :show="show" :ready="!!options" :load-error="error" origin-key="production-plan-editor"
    :title="edit ? '编辑生产计划' : '新建生产计划'" :data="form.lines" :columns="columns" :min-table-width="1220"
    :busy="busy" :disabled="disabled" :submit-disabled="!!problem || !options" :add-disabled="form.lines.length >= 100"
    lines-title="生产安排" add-label="添加产品" empty-text="添加产品后，安排产量、开工日与完工日。"
    hint="保存草稿后通过单据审批批准，再按产品分批生成生产工单。"
    @update:show="emit('update:show', $event)" @invalidated="emit('update:show', false)" @add-material="addLine" @submit="save">
    <template #basicInfo>
      <label>计划名称<AppInput v-model.trim="form.reference" required maxlength="100" placeholder="例如：十月第三周生产安排" :disabled="disabled" /></label>
      <label>编制 / 修改依据<AppInput v-model.trim="form.reason" required maxlength="500" placeholder="订单交付或备货安排" :disabled="disabled" /></label>
      <label>备注<AppInput v-model.trim="form.note" maxlength="500" :disabled="disabled" /></label>
    </template>
    <template #cell-product="{ row }">
      <div class="stack plan-product">
        <WorkspaceMaterialSelect use="can_produce" :model-value="materialId(row)" :materials="options?.materials ?? []" :compact="true"
          required placeholder="选择生产产品" aria-label="计划生产产品" :disabled="disabled" @update:model-value="selectProduct(row, $event)" />
        <WorkspaceSelect v-model="row.bom_id" required aria-label="计划 BOM 版本" :disabled="disabled || !materialId(row)"
          :options="(options?.boms ?? []).filter(bom => bom.material_id === materialId(row)).map(bom => ({ value: bom.id, label: `BOM V${bom.version} · 基准 ${bom.base_quantity} ${bom.unit}` }))" />
      </div>
    </template>
    <template #cell-sales="{ row }"><WorkspaceSelect v-model="row.sales_order_line_id" :options="salesOptions(row)" aria-label="计划销售来源" :disabled="disabled || !materialId(row)" /></template>
    <template #cell-quantity="{ row }"><AppInput v-model="row.quantity" type="number" hide-number-controls min="0.001" max="1000000" step="0.001" required aria-label="计划产量" :disabled="disabled" /></template>
    <template #cell-dates="{ row }"><div class="stack plan-dates">
      <MrpDate v-model="row.start_date" :min="options?.today" aria-label="计划开工日" :disabled="disabled" />
      <MrpDate v-model="row.end_date" :min="row.start_date" aria-label="计划完工日" :disabled="disabled" />
    </div></template>
    <template #cell-warehouse="{ row }"><WorkspaceSelect v-model="row.warehouse_id" required aria-label="计划完工仓库" :disabled="disabled"
      :options="(options?.warehouses ?? []).map(item => ({ value: item.id, label: item.name }))" /></template>
    <template #cell-priority="{ row }"><WorkspaceSelect v-model="row.priority" :options="priorities" aria-label="计划优先级" :disabled="disabled" /></template>
    <template #cell-actions="{ row }"><AppButton size="small" :disabled="disabled" @click="form.lines.splice(form.lines.indexOf(row), 1)">移除</AppButton></template>
    <template #afterLines>
      <p v-if="!options?.boms.length" role="status">暂无可生产的启用 BOM，请先在产品与 BOM 中维护。</p>
      <p v-if="problem" class="muted" role="status">{{ problem }}</p><p v-if="error" role="alert">{{ error }}</p>
      <p class="muted">日期按日历日安排。销售来源仅分配生产数量；批准后的计划自动参与物料需求计算。</p>
    </template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 表格内两行日期与产品选择保持紧凑，窄窗口沿公共单据表横向滚动。 */
.plan-product, .plan-dates { gap: 8px; }
</style>
