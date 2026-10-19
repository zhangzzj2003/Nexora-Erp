<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { MrpPolicy, MrpPolicyInput } from '../../../../../shared/mrp-api'
import { mrpMode, mrpQuantityValid } from './mrp-display'
const store = usePiniaAppStore()
const { mrpOptions: options, mrpPolicyChanges: changes, user, busy, connectionLost, error } = storeToRefs(store)
const selected = ref<number | null>(null)
const form = ref<MrpPolicyInput>({version:0,supply_mode:'auto',lead_time_days:0,safety_stock:'0',minimum_quantity:'0',multiple_quantity:'0',reason:''})
const query = ref('')
const rows = computed(() => (options.value?.policies ?? []).map(row => ({...row,material:options.value!.materials.find(value=>value.id===row.material_id)!}))
  .filter(row => `${row.material.sku} ${row.material.name}`.toLowerCase().includes(query.value.toLowerCase().trim())))
const columns = [{key:'material',title:'物料',width:'220'}, {key:'supply_mode',title:'供给方式',width:'210'},
  {key:'lead_time_days',title:'提前期（日历日）'}, {key:'safety_stock',title:'安全库存'}, {key:'minimum_quantity',title:'最小批量'},
  {key:'multiple_quantity',title:'批量倍数'}, {key:'actions',title:'参数与审计',width:'180'}]
// 显式供给方式同步产品用途；已有失效配置保留可见，必须重选后保存。
const selectedMaterial = computed(() => options.value?.materials.find(row => row.id === selected.value))
const modes = computed(() => (['auto','buy','make'] as const).map(value => ({value,label:mrpMode[value],
  disabled: value === 'buy' ? selectedMaterial.value?.can_purchase === false
    : value === 'make' ? selectedMaterial.value?.can_produce === false : false})))
const disabled = computed(() => busy.value || connectionLost.value)
const invalid = computed(() => modes.value.some(row => row.value === form.value.supply_mode && row.disabled) || !form.value.reason.trim() || !Number.isInteger(form.value.lead_time_days)
  || form.value.lead_time_days < 0 || form.value.lead_time_days > 365
  || ![form.value.safety_stock,form.value.minimum_quantity,form.value.multiple_quantity].every(mrpQuantityValid))
const name = computed(() => options.value?.materials.find(row=>row.id===selected.value)?.name)
async function open(row: MrpPolicy): Promise<void> {
  selected.value = row.material_id
  const { version, supply_mode, lead_time_days, safety_stock, minimum_quantity, multiple_quantity } = row
  form.value = { version, supply_mode, lead_time_days, safety_stock, minimum_quantity, multiple_quantity, reason:'' }
  await store.loadMrpPolicyChanges(row.material_id)
}
async function save(): Promise<void> {
  if (selected.value && !invalid.value && await store.saveMrpPolicy(selected.value,{...form.value})) selected.value = null
}
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => { selected.value = null })
</script>
<template>
  <section class="stack">
    <WorkspaceTable title="物料计划参数" :show-title="false" :columns="columns" :data="rows" :min-table-width="1000">
      <template #filters><label>搜索物料<AppInput v-model="query" placeholder="物料编码或名称" /></label></template>
      <template #cell-material="{ row }">{{ row.material.sku }} · {{ row.material.name }}<span class="muted mrp-line">{{ row.material.unit }} · {{ row.version ? 'v' + row.version : '尚未配置，使用默认值' }}</span></template>
      <template #cell-supply_mode="{ row }">{{ mrpMode[row.supply_mode] }}</template>
      <template #cell-actions="{ row }"><AppButton size="small" :disabled="disabled" @click="open(row)">{{ store.can('mrp.configure') ? '维护与审计' : '查看审计' }}</AppButton></template>
      <template #empty>{{ query ? '没有匹配的物料。' : '尚无物料，请先维护基础资料。' }}</template>
    </WorkspaceTable>
    <section v-if="selected" class="card mrp-panel">
      <div class="mrp-toolbar"><h2>{{ name }} · 计划参数</h2><AppButton @click="selected=null">关闭参数</AppButton></div>
      <p>最小批量和批量倍数为 0 时不限制；安全库存为 0 时不补储备。默认自动方式沿用启用 BOM；明确选采购会停止展开该物料的组件。</p>
      <form v-if="store.can('mrp.configure')" class="mrp-editor" @submit.prevent="save">
        <div class="form-grid">
          <label>供给方式<WorkspaceSelect v-model="form.supply_mode" :options="modes" :disabled="disabled" /></label>
          <label>提前期（日历日）<AppInput :model-value="String(form.lead_time_days)" type="number" required min="0" max="365" step="1" :disabled="disabled" @update:model-value="value=>form.lead_time_days=Number(value)" /></label>
          <label>安全库存<AppInput v-model="form.safety_stock" inputmode="decimal" required :disabled="disabled" /></label>
          <label>最小批量<AppInput v-model="form.minimum_quantity" inputmode="decimal" required :disabled="disabled" /></label>
          <label>批量倍数<AppInput v-model="form.multiple_quantity" inputmode="decimal" required :disabled="disabled" /></label>
          <label>修改原因<AppInput v-model.trim="form.reason" required maxlength="500" :disabled="disabled" /></label>
        </div>
        <p>保存后旧计划不会改变，须新建重算。版本变化会拒绝保存，请重新打开参数。</p>
        <p v-if="error" role="alert">{{ error }}</p>
        <AppButton type="submit" variant="primary" :disabled="disabled || invalid">保存参数 v{{ form.version }}</AppButton>
      </form>
      <h3>参数审计</h3><p v-if="!changes.length" class="muted">尚无已保存的参数变更。</p>
      <NCollapse><AppCollapseItem v-for="change in changes" :key="change.id" :name="String(change.id)" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${change.reason}`">
        <dl class="mrp-facts"><template v-for="key in ['supply_mode','lead_time_days','safety_stock','minimum_quantity','multiple_quantity'] as const" :key="key"><dt>{{ ({supply_mode:'供给方式',lead_time_days:'提前期',safety_stock:'安全库存',minimum_quantity:'最小批量',multiple_quantity:'批量倍数'})[key] }}</dt><dd>{{ key==='supply_mode' ? (change.before ? mrpMode[change.before[key]] : '默认') : (change.before?.[key] ?? '默认') }} → {{ key==='supply_mode' ? mrpMode[change.after[key]] : change.after[key] }}</dd></template></dl>
      </AppCollapseItem></NCollapse>
    </section>
  </section>
</template>
