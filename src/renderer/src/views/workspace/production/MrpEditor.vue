<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import MrpDate from './MrpDate.vue'
import { mrpDraftError, mrpSourceLabel, mrpSourceStatus } from './mrp-display'
const store = usePiniaAppStore()
const { mrpForm: form, mrpOptions: options, busy, mrpLoading: loading, connectionLost, error } = storeToRefs(store)
const emit = defineEmits<{ saved: [] }>()
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const problem = computed(() => mrpDraftError(form.value, options.value?.today ?? ''))
const materialOptions = computed(() => [{ value: 0, label: '选择物料', disabled: true }, ...(options.value?.materials ?? []).map(row => ({value:row.id,label:`${row.sku} · ${row.name}`}))])
const name = (id: number) => options.value?.materials.find(row => row.id === id)?.name ?? '#' + id
const dates = computed(() => [
  ...(options.value?.demands ?? []).map(row => ({ ...row, direction: '需求', schedule: form.value.demand_dates.find(value => value.key === row.key) })),
  ...(options.value?.supplies ?? []).map(row => ({ ...row, direction: '预计供给', schedule: form.value.supply_dates.find(value => value.key === row.key) }))
])
const sourceColumns = [{key:'direction',title:'方向',width:'110'}, {key:'source',title:'来源',width:'270'},
  {key:'material',title:'物料',width:'180'}, {key:'quantity',title:'剩余数量',width:'130'}, {key:'date',title:'需求 / 到货日',width:'210'}]
const manualColumns = [{key:'material',title:'物料',width:'240'}, {key:'quantity',title:'需求数量',width:'160'},
  {key:'due_date',title:'需求日',width:'200'}, {key:'reference',title:'来源编号',width:'220'}, {key:'actions',title:'操作',width:'90'}]
async function save(): Promise<void> { if (options.value && !problem.value && !disabled.value && await store.createMrpPlan()) emit('saved') }
</script>
<template>
  <form class="mrp-editor" @submit.prevent="save">
    <p>逐项安排当前未执行的销售需求、采购与工单供给日期，另加手工需求。未下达工单的待领组件按计划起日计入；全部仓库合并计算，实际发料前须核对目标仓库。</p>
    <p v-if="!options" role="alert">来源尚不可用。恢复连接后重新读取；已填输入保留。</p>
    <div class="form-grid">
      <label>计划编号<AppInput v-model.trim="form.reference" required maxlength="80" :disabled="disabled" placeholder="本次计算的唯一依据编号" /></label>
      <label>计划起日（服务端 UTC）<MrpDate v-model="form.start_date" :min="options?.today" :disabled="disabled" aria-label="计划起日" /></label>
      <label>编制依据<AppInput v-model.trim="form.reason" required maxlength="500" :disabled="disabled" /></label>
    </div>
    <WorkspaceTable material-supply title="现有需求与预计供给" :columns="sourceColumns" :data="dates" :min-table-width="950">
      <template #cell-source="{ row }">{{ mrpSourceLabel(row) }}<span class="muted mrp-line">原单状态：{{ mrpSourceStatus(row.status) }}</span></template>
      <template #cell-material="{ row }">{{ name(row.material_id) }}</template>
      <template #cell-date="{ row }"><MrpDate v-if="row.schedule" v-model="row.schedule.due_date" :min="form.start_date" :disabled="disabled" :aria-label="mrpSourceLabel(row) + '日期'" /><span v-else>{{ row.due_date }} · 前次转单日期</span></template>
      <template #empty>暂无未执行销售需求或预计供给；可添加手工需求。</template>
    </WorkspaceTable>
    <WorkspaceTable material-supply title="额外手工需求" :columns="manualColumns" :data="form.manual_demands" :min-table-width="950">
      <template #actions><AppButton :disabled="disabled || form.manual_demands.length >= 500" @click="form.manual_demands.push({material_id:0,quantity:'1',due_date:'',reference:''})">添加手工需求</AppButton></template>
      <template #cell-material="{ row }"><WorkspaceMaterialSelect :materials="options?.materials ?? []" v-model="row.material_id" :options="materialOptions" :disabled="disabled" aria-label="手工需求物料" required /></template>
      <template #cell-quantity="{ row }"><AppInput v-model="row.quantity" required inputmode="decimal" pattern="[0-9]{1,7}(\.[0-9]{1,3})?" :disabled="disabled" aria-label="手工需求数量" /></template>
      <template #cell-due_date="{ row }"><MrpDate v-model="row.due_date" :min="form.start_date" :disabled="disabled" aria-label="手工需求日期" /></template>
      <template #cell-reference="{ row }"><AppInput v-model.trim="row.reference" required maxlength="100" :disabled="disabled" aria-label="手工需求来源编号" /></template>
      <template #cell-actions="{ row }"><AppButton size="small" :disabled="disabled" @click="form.manual_demands.splice(form.manual_demands.indexOf(row),1)">移除</AppButton></template>
      <template #empty>没有额外需求。只按现有来源和安全库存计算。</template>
    </WorkspaceTable>
    <p v-if="options?.reservations.length">另有 {{ options.reservations.length }} 条工单待领组件，按起日计入毛需求；计算结果可逐行查看来源。</p>
    <p>保存时由服务端读取当前库存、BOM 与参数，固定新的计算结果。没有产能及合格率保证；提前期按日历日，单次最多 730 天。</p>
    <p v-if="problem" role="status">{{ problem }}</p><p v-if="error" role="alert">{{ error }}</p>
    <AppButton type="submit" variant="primary" :disabled="disabled || !options || !!problem">计算并保存草稿</AppButton>
  </form>
</template>
