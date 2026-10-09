<script setup lang="ts">
import { computed } from 'vue'
import { NDatePicker } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import { datePickerString, vDateField } from '../../utils/date-field'
import { lotAllocation, type LotEditorPart } from '../../utils/lot-allocation'

// 单据明细与批次草稿保持原对象引用；跳过的物料仍留一行，随时可恢复收货。
export interface InboundLotTableLine {
  id: number
  sku: string
  name: string
  unit: string
  expected: string
  lots: LotEditorPart[]
}
const props = defineProps<{ lines: InboundLotTableLine[]; disabled?: boolean }>()
const emit = defineEmits<{ add: [id: number]; remove: [id: number, index: number] }>()
// 空批次占位与真实批次使用明确的联合类型，模板不会误写空行。
interface InboundLotTableRow {
  line: InboundLotTableLine
  part: LotEditorPart | null
  index: number
  allocation: ReturnType<typeof lotAllocation>
}
const rows = computed(() => props.lines.flatMap<InboundLotTableRow>(line => {
  const allocation = lotAllocation(line.expected, line.lots, true)
  return line.lots.length
    ? line.lots.map((part, index) => ({ line, part, index, allocation }))
    : [{ line, part: null, index: 0, allocation }]
}))
const columns = [
  { key: 'material', title: '物料', width: '220' },
  { key: 'expected', title: '待入库', width: '100' },
  { key: 'quantity', title: '本次批次数量', width: '150' },
  { key: 'source', title: '来源批号（可选）', width: '180' },
  { key: 'manufactured', title: '生产日期（可选）', width: '165' },
  { key: 'expires', title: '失效日期（可选）', width: '165' },
  { key: 'actions', title: '操作', width: '180' }
]
function add(line: InboundLotTableLine): void {
  if (!props.disabled && line.lots.length < 20) emit('add', line.id)
}
function remove(line: InboundLotTableLine, index: number): void {
  // 禁用、索引范围及空行共同保护事件，避免旧按钮回调删除错误批次。
  if (!props.disabled && index >= 0 && index < line.lots.length) emit('remove', line.id, index)
}
</script>

<template>
  <WorkspaceTable title="本次入库批次" :show-title="false" :data="rows" :columns="columns"
    :min-table-width="1160" stretch-columns class="inbound-lot-table">
    <template #cell-material="{ row }">
      <div v-if="row.index === 0" class="inbound-lot-material"><strong>{{ row.line.sku }}</strong><span>{{ row.line.name }}</span></div>
      <span v-else class="inbound-lot-muted">{{ row.line.sku }} · 批次 {{ row.index + 1 }}</span>
    </template>
    <template #cell-expected="{ row }">
      <span v-if="row.index === 0">{{ row.line.expected }} {{ row.line.unit }}</span>
      <span v-else class="inbound-lot-muted">—</span>
    </template>
    <template #cell-quantity="{ row }">
      <AppInput v-if="row.part" v-model.trim="row.part.quantity" inputmode="decimal" required :disabled="disabled"
        :aria-label="`${row.line.sku} 第 ${row.index + 1} 行批次数量`" />
      <span v-else class="inbound-lot-muted">本次不入库</span>
      <!-- 只显示需要处理的差额，不再为每个物料重复展示大段汇总。 -->
      <small v-if="row.index === 0 && row.part && row.allocation.status !== 'complete'" role="status"
        :class="{ 'inbound-lot-error': ['invalid', 'over'].includes(row.allocation.status) }">
        {{ row.allocation.status === 'invalid' ? '请填写有效数量' : `${row.allocation.status === 'over' ? '超出' : '本次后待入库'} ${row.allocation.remaining} ${row.line.unit}` }}
      </small>
    </template>
    <template #cell-source="{ row }">
      <AppInput v-if="row.part" v-model.trim="row.part.supplier_lot" maxlength="100" placeholder="未提供则留空"
        :disabled="disabled" :aria-label="`${row.line.sku} 第 ${row.index + 1} 行来源批号`" />
      <span v-else class="inbound-lot-muted">—</span>
    </template>
    <template #cell-manufactured="{ row }">
      <label v-if="row.part" class="inbound-lot-date"><span class="inbound-lot-label">{{ row.line.sku }} 第 {{ row.index + 1 }} 行生产日期</span>
        <NDatePicker v-date-field="{ min: '2000-01-01', max: '2099-12-31' }" to="body" type="date"
          format="yyyy-MM-dd" value-format="yyyy-MM-dd" placeholder="选择日期" :formatted-value="row.part.manufactured_on ?? null" :disabled="disabled"
          @update:formatted-value="value => { if (row.part) row.part.manufactured_on = datePickerString(value) || null }" />
      </label>
      <span v-else class="inbound-lot-muted">—</span>
    </template>
    <template #cell-expires="{ row }">
      <label v-if="row.part" class="inbound-lot-date"><span class="inbound-lot-label">{{ row.line.sku }} 第 {{ row.index + 1 }} 行失效日期</span>
        <NDatePicker v-date-field="{ min: '2000-01-01', max: '2099-12-31' }" to="body" type="date"
          format="yyyy-MM-dd" value-format="yyyy-MM-dd" placeholder="选择日期" :formatted-value="row.part.expires_on ?? null" :disabled="disabled"
          @update:formatted-value="value => { if (row.part) row.part.expires_on = datePickerString(value) || null }" />
      </label>
      <span v-else class="inbound-lot-muted">—</span>
    </template>
    <template #cell-actions="{ row }">
      <div class="inbound-lot-actions">
        <AppButton v-if="row.index === 0" type="button" size="small" :disabled="disabled || row.line.lots.length >= 20"
          :aria-label="`${row.line.sku} 添加批次`" @click="add(row.line)">添加批次</AppButton>
        <AppButton v-if="row.part" type="button" size="small" :disabled="disabled"
          :aria-label="`${row.line.sku} 移除第 ${row.index + 1} 个批次`" @click="remove(row.line, row.index)">移除</AppButton>
      </div>
    </template>
  </WorkspaceTable>
</template>

<style scoped>
/* 一张表承载全部物料，横向滚动和列宽调整复用工作台表格。 */
.inbound-lot-table { padding: 0; border: 0; background: transparent; box-shadow: none; }
:root[data-theme='dark'] .inbound-lot-table { background: transparent; box-shadow: none; }
.inbound-lot-material { display: grid; gap: 6px; overflow-wrap: anywhere; }
.inbound-lot-material span, .inbound-lot-muted { color: var(--workspace-field-muted); }
.inbound-lot-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.inbound-lot-date { display: block; position: relative; }
.inbound-lot-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.inbound-lot-error { color: #b94438; }
:root[data-theme='dark'] .inbound-lot-error { color: #ffaaa2; }
</style>
