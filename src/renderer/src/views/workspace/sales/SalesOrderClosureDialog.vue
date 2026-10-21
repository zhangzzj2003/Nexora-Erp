<script setup lang="ts">
import {computed, ref} from 'vue'
import {storeToRefs} from 'pinia'
import type {SalesOrder} from '../../../../../shared/erp-api'
import {documentLabel} from '../../../../../shared/document-numbering'
import AppModal from '../../../components/app/AppModal.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import {usePiniaAppStore} from '../../../store/app-store'
const target = defineModel<SalesOrder | null>({required:true})
const store = usePiniaAppStore(), {busy, connectionLost, error} = storeToRefs(store)
const reason = ref('')
const columns = [{key:'material',title:'物料',width:'260'}, {key:'quantity',title:'订单数量',width:'120'},
  {key:'shipped_quantity',title:'终止时已出库',width:'140'}, {key:'closed_quantity',title:'终止交付量',width:'140'}]
const rows = computed(()=>target.value?.closure?.lines ?? target.value?.lines.map(line=>({
  ...line, closed_quantity:line.remaining_quantity})) ?? [])
async function submit(): Promise<void> {
  if (!target.value || target.value.closure || busy.value || connectionLost.value) return
  const saved = await store.closeSalesOrder({orderId:target.value.id, reason:reason.value,
    expected_lines:target.value.lines.map(line=>({line_id:line.id, shipped_quantity:line.shipped_quantity}))})
  if (saved) target.value = null
}
</script>
<template>
  <!-- 终止操作与已保存证据共用单一弹窗，保存成功后不再提供重复提交入口。 -->
  <AppModal preset="card" :show="!!target" :busy="busy" :title="target?.closure ? '剩余交付终止记录' : '终止剩余交付'"
    :style="{width:'min(940px, calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}"
    @update:show="value=>{if(!value)target=null}" @invalidated="target=null">
    <form v-if="target" class="stack" @submit.prevent="submit">
      <p>{{ documentLabel(target) }} · {{ target.customer_name }}</p>
      <p class="muted">终止后不再安排出库，原订单数量、金额和已发生的库存、应收记录保留。后续退货或冲销仍走原流程，订单不会自动恢复交付。</p>
      <WorkspaceTable :data="rows" :columns="columns" title="终止交付明细" row-key="id" :show-title="false">
        <template #cell-material="{row}">{{ row.sku }} · {{ row.material_name }}（{{ row.unit }}）</template>
      </WorkspaceTable>
      <template v-if="target.closure">
        <p>{{ target.closure.created_by_name }} · {{ store.localTime(target.closure.created_at) }}</p>
        <p>终止原因：{{ target.closure.reason }}</p>
      </template>
      <template v-else>
        <p class="muted">请先处理待出库草稿及相关生产、采购待办。本操作终止整张订单的剩余交付，无法直接撤销。</p>
        <label>终止原因<AppInput v-model="reason" type="textarea" required :maxlength="500" :disabled="busy" placeholder="填写客户变更、协商结果等依据" /></label>
        <p v-if="error" role="alert" class="inline-error">{{ error }}</p>
      </template>
      <footer class="actions">
        <AppButton :disabled="busy" @click="target=null">{{ target.closure ? '关闭' : '暂不终止' }}</AppButton>
        <AppButton v-if="!target.closure" type="submit" tone="warning" variant="primary"
          :disabled="busy || connectionLost || !reason.trim()">确认终止剩余交付</AppButton>
      </footer>
    </form>
  </AppModal>
</template>
<style scoped>
/* 与销售单据公共弹窗保持一致，操作始终在明细和原因之后靠右。 */
.actions {display:flex;justify-content:flex-end;gap:10px}
</style>
