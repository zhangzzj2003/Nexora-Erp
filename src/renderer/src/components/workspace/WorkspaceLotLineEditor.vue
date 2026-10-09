<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { NDatePicker } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import { datePickerString, vDateField } from '../../utils/date-field'
import { lotAllocation } from '../../utils/lot-allocation'
import type { LotEditorPart } from '../../utils/lot-allocation'
import type { WorkspaceSelectOption } from '../../utils/workspace-select'

// 采购入库的批次登记也可查看原物料供需；其他批次业务显式传编号后才加载。
const WorkspaceMaterialSupplyCell = defineAsyncComponent(() => import('./WorkspaceMaterialSupplyCell.vue'))

// 表格行保留业务草稿的对象引用，失败时仍能继续编辑，不另建跨页面状态。
const props = withDefaults(defineProps<{
  lots: LotEditorPart[]
  materialId?: number
  sku?: string
  materialName?: string
  unit?: string
  expected: string
  expectedLabel?: string
  quantityLabel?: string
  sourceLabel?: string
  selectable?: boolean
  newLotValue?: number | null
  showSource?: boolean
  options?: readonly WorkspaceSelectOption<number | null>[]
  disabled?: boolean
  // 仅分批入库启用，空批次表示本物料本次尚未到货。
  allowPartial?: boolean
}>(), { sku: '', materialName: '', unit: '', expectedLabel: '应分配', quantityLabel: '批次数量',
  sourceLabel: '来源批号', selectable: false, showSource: true, options: () => [], disabled: false })
const emit = defineEmits<{ add: []; remove: [index: number] }>()
const rows = computed(() => props.lots.map((part, index) => ({ part, index })))
const allocation = computed(() => lotAllocation(props.expected, props.lots, props.allowPartial))
const hasNewFields = computed(() => !props.selectable || props.newLotValue !== undefined)
const columns = computed(() => [
  { key: 'index', title: '序号', width: '60' },
  ...(props.selectable ? [{ key: 'lot', title: '实物批次', width: hasNewFields.value ? '270' : '440' }] : []),
  { key: 'quantity', title: props.quantityLabel, width: '140' },
  ...(hasNewFields.value ? [
    ...(props.showSource ? [{ key: 'source', title: `${props.sourceLabel}（可选）`, width: '180' }] : []),
    { key: 'manufactured', title: '生产日期（可选）', width: '170' },
    { key: 'expires', title: '失效日期（可选）', width: '170' }
  ] : []),
  { key: 'actions', title: '操作', width: '80' }
])
const minWidth = computed(() => columns.value.reduce((total, column) => total + Number(column.width), 0))
function isNewPart(part: LotEditorPart): boolean {
  return !props.selectable || (props.newLotValue !== undefined && part.lot_id === props.newLotValue)
}
function add(): void {
  if (!props.disabled && props.lots.length < 20) emit('add')
}
function remove(index: number): void {
  // 分批收货可移除最后一行以暂不入库，其他业务仍要求保留至少一批。
  if (!props.disabled && (props.allowPartial || props.lots.length > 1)) emit('remove', index)
}
</script>

<template>
  <section class="lot-line-editor" :aria-label="`${sku} ${materialName} 批次明细`">
    <header class="lot-line-heading">
      <div class="lot-line-material"><strong>{{ sku }}</strong><span>{{ materialName }}</span></div>
      <AppButton type="button" size="small" :disabled="disabled || lots.length >= 20" @click="add">添加批次</AppButton>
    </header>
    <div v-if="materialId" class="lot-line-supply"><WorkspaceMaterialSupplyCell :material-id="materialId" :active="!disabled" /></div>
    <div class="lot-line-summary" :class="`is-${allocation.status}`" role="status" aria-live="polite" aria-atomic="true">
      <span>{{ expectedLabel }} <strong>{{ allocation.expected }}</strong> {{ unit }}</span>
      <span>{{ allowPartial ? '本次实收' : '已分配' }} <strong>{{ allocation.allocated }}</strong> {{ unit }}</span>
      <span>{{ allocation.status === 'over' ? '超出' : allowPartial ? '本次后待入库' : '剩余' }} <strong>{{ allocation.remaining }}</strong> {{ unit }}</span>
      <span class="lot-line-state">{{ allocation.status === 'complete' ? '数量已核对' : allocation.status === 'invalid' ? '请填写有效数量' : allocation.status === 'over' ? '分配超出' : allowPartial ? lots.length ? '可分批入库' : '本次不入库' : '待分配' }}</span>
    </div>
    <p v-if="$slots.default" class="lot-line-note"><slot /></p>
    <WorkspaceTable :title="`${sku || materialName} 批次明细`" :show-title="false" :data="rows"
      :columns="columns" :min-table-width="minWidth" class="lot-line-table">
      <template #cell-index="{ row }">{{ row.index + 1 }}</template>
      <template #cell-lot="{ row }">
        <WorkspaceSelect :model-value="row.part.lot_id === undefined ? 0 : row.part.lot_id" :options="options" required :disabled="disabled"
          :aria-label="`${sku} 第 ${row.index + 1} 行实物批次`" @update:model-value="value => row.part.lot_id = value" />
      </template>
      <template #cell-quantity="{ row }">
        <AppInput v-model.trim="row.part.quantity" inputmode="decimal" required :disabled="disabled"
          :aria-label="`${sku} 第 ${row.index + 1} 行${quantityLabel}`" />
      </template>
      <template #cell-source="{ row }">
        <AppInput v-if="isNewPart(row.part)" v-model.trim="row.part.supplier_lot" maxlength="100"
          placeholder="未提供则留空" :disabled="disabled" :aria-label="`${sku} 第 ${row.index + 1} 行${sourceLabel}`" />
        <span v-else class="muted">沿用原批次</span>
      </template>
      <template #cell-manufactured="{ row }">
        <!-- 原生标签关联日期输入，读屏时能够区分物料、行号和日期用途。 -->
        <label v-if="isNewPart(row.part)" class="lot-date-field">
        <span class="lot-field-label">{{ sku }} 第 {{ row.index + 1 }} 行生产日期</span>
        <NDatePicker v-date-field="{ min: '2000-01-01', max: '2099-12-31' }"
          to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
          :formatted-value="row.part.manufactured_on ?? null" :disabled="disabled"
          @update:formatted-value="value => row.part.manufactured_on = datePickerString(value) || null" />
        </label>
        <span v-else class="muted">沿用原批次</span>
      </template>
      <template #cell-expires="{ row }">
        <label v-if="isNewPart(row.part)" class="lot-date-field">
        <span class="lot-field-label">{{ sku }} 第 {{ row.index + 1 }} 行失效日期</span>
        <NDatePicker v-date-field="{ min: '2000-01-01', max: '2099-12-31' }"
          to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
          :formatted-value="row.part.expires_on ?? null" :disabled="disabled"
          @update:formatted-value="value => row.part.expires_on = datePickerString(value) || null" />
        </label>
        <span v-else class="muted">沿用原批次</span>
      </template>
      <template #cell-actions="{ row }">
        <AppButton type="button" size="small" :disabled="disabled || (!allowPartial && lots.length <= 1)"
          :aria-label="`${sku} 移除第 ${row.index + 1} 个批次`" @click="remove(row.index)">移除</AppButton>
      </template>
    </WorkspaceTable>
  </section>
</template>

<style scoped>
/* 当前供需只读展示，批次数量仍按本单原始目标独立核对。 */
.lot-line-supply { width: min(320px, 100%); margin-bottom: 12px; }
/* 物料信息只出现一次，批次按紧凑表格排列，窄窗口沿用公共横向滚动。 */
.lot-line-editor { width: 100%; min-width: 0; }
.lot-line-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.lot-line-heading > :last-child { flex-shrink: 0; }
.lot-line-material { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 14px; min-width: 0; font-size: 14px; overflow-wrap: anywhere; }
.lot-line-material span { color: var(--workspace-field-muted); }
.lot-line-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 22px; margin-bottom: 12px; font-size: 12px; color: var(--workspace-field-muted); }
.lot-line-summary strong { color: var(--workspace-field-text); font-variant-numeric: tabular-nums; }
.lot-line-state { margin-left: auto; }
.is-complete .lot-line-state { color: #16805b; }
.is-over .lot-line-state, .is-invalid .lot-line-state { color: #b94438; }
:root[data-theme='dark'] .is-complete .lot-line-state { color: #70d9b4; }
:root[data-theme='dark'] .is-over .lot-line-state, :root[data-theme='dark'] .is-invalid .lot-line-state { color: #ffaaa2; }
.lot-line-note { margin: 0 0 12px; font-size: 12px; color: var(--workspace-field-muted); }
.lot-date-field { display: block; position: relative; }
.lot-field-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.lot-line-table { padding: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
:root[data-theme='dark'] .lot-line-table { background: transparent; box-shadow: none; }
@media (max-width: 650px) { .lot-line-state { margin-left: 0; } }
</style>
