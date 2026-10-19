<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import AppButton from '../app/AppButton.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import WorkspaceMaterialName from './WorkspaceMaterialName.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { useMaterialFlowStore, materialFlowLabels, materialFlowRoutes, materialFlowStatusLabel } from '../../store/modules/material-flow-store'
import { routeByKey } from '../../router/workspace-routes'
import { useDialogPreparation } from '../../composables/use-dialog-presentation'
import { captureDialogOrigin } from '../../utils/dialog-origin'
import type { MaterialFlowKind } from '../../../../shared/material-flow-api'

// 工单保留四个明确区域，跳转时携带工单约束，仓库列表与生产侧看到同一批单据。
const props = defineProps<{ orderId: number }>()
const app = usePiniaAppStore(), flow = useMaterialFlowStore(), router = useRouter()
const { orders, loading, readErrors, available } = storeToRefs(flow)
const summary = computed(() => orders.value[props.orderId])
const sections = computed(() => ([['dispatch', 'dispatches'], ['receipt', 'receipts'], ['exchange', 'exchanges'], ['return', 'returns']] as const)
  .map(([kind, field]) => ({ kind, title: materialFlowLabels[kind], items: summary.value?.[field] ?? [], hint: {
    dispatch: '仓库按工单发出，支持分批备料与出库。', receipt: '生产核对实物后签收，差额持续待处理。',
    exchange: '旧料交接后补发，新料签收后才完成。', return: '交回可用余料，仓库接收后才增加库存。'
  }[kind] })))
const pending = ref(false), preparationError = ref('')
let requestGeneration = 0, pendingOrder = 0
function cancelRead(): void {
  requestGeneration++
  if (pendingOrder) flow.cancelRead(`order:${pendingOrder}`)
  pendingOrder = 0; pending.value = false
}
async function load(): Promise<void> {
  cancelRead(); preparationError.value = ''
  if (!available.value || !props.orderId) return
  const id = props.orderId, ticket = requestGeneration
  pendingOrder = id; pending.value = true
  const value = await flow.loadOrder(id)
  if (ticket !== requestGeneration || !available.value || props.orderId !== id) return
  pendingOrder = 0
  if (!value) preparationError.value = readErrors.value[`order:${id}`] || '工单材料核对读取失败，请重新打开详情后重试。'
  pending.value = false
}
// 工单首屏包括这四块材料摘要；同步挂载后登记屏障，摘要到齐才让父详情展开。
useDialogPreparation(pending, preparationError)
watch([() => props.orderId, available], () => void load(), { immediate: true })
onBeforeUnmount(cancelRead)
async function open(kind: MaterialFlowKind, id?: number, event?: Event): Promise<void> {
  if (!available.value || pending.value || preparationError.value) return
  if (id) captureDialogOrigin(`ProductionMaterialFlowView:${kind}:detail`, event)
  app.closeDocumentApproval()
  await router.push({ path: routeByKey(materialFlowRoutes[kind]).path, query: { work_order_id: props.orderId, ...(id ? { document_id: id } : {}) } })
}
const columns = [{ key: 'material', title: '物料', width: '260' }, { key: 'required', title: '正常需求', width: '110' },
  { key: 'signed', title: '累计领用', width: '160' }, { key: 'transit', title: '已发未签', width: '110' }, { key: 'returned', title: '退回 / 损坏', width: '150' },
  { key: 'available', title: '有效 / 预留 / 可用', width: '190' }]
</script>
<template>
  <section v-if="available" class="work-order-material-flow" aria-label="工单发料、领料、换料、退料">
    <div class="flow-sections"><section v-for="section in sections" :key="section.kind"><header><h3>{{ section.title }}</h3><span class="pill">{{ section.items.length }} 单</span></header><p>{{ section.hint }}</p>
      <div v-for="item in section.items" :key="item.id" class="flow-order-link"><AppButton variant="text" :disabled="pending || !!preparationError" @click="open(section.kind, item.id, $event)">{{ item.document_no }}</AppButton><small>{{ materialFlowStatusLabel(item.kind, item.status) }}</small></div>
      <AppButton :disabled="app.connectionLost || pending || !!preparationError" @click="open(section.kind)">查看与办理{{ section.title.slice(2) }}</AppButton>
    </section></div>
    <WorkspaceTable title="工单材料核对" :columns="columns" :data="summary?.lines ?? []" :loading="loading[`order:${orderId}`]" :error="preparationError" :min-table-width="780">
      <template #cell-material="{ row }"><WorkspaceMaterialName :name="`${row.sku} · ${row.material_name}`" :material-id="row.material_id" :material="row.material" /></template><template #cell-required="{ row }">{{ row.required_quantity }} {{ row.unit }}</template>
      <template #cell-signed="{ row }">{{ row.signed_quantity }}<small v-if="Number(row.historical_direct_quantity) > 0">含历史直接领料 {{ row.historical_direct_quantity }}（无签收记录）</small></template><template #cell-transit="{ row }">{{ row.in_transit_quantity ?? '0' }}</template><template #cell-returned="{ row }">{{ row.returned_quantity }} / {{ row.damaged_quantity }}</template>
      <template #cell-available="{ row }">{{ row.effective_quantity }} / {{ row.reserved_quantity }} / {{ row.available_quantity ?? '—' }}</template>
    </WorkspaceTable>
  </section>
</template>
<style scoped>
/* 四块业务在宽屏并列，窄屏自然换行，不压缩单号和实际数量。 */
.work-order-material-flow { margin: 18px 0 24px; }
.work-order-material-flow small { display: block; color: var(--workspace-field-muted); font-size: 12px; }
.flow-sections { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
.flow-sections > section { padding: 14px; border: 1px solid var(--workspace-field-border); border-radius: 12px; background: var(--workspace-field-background); }
.flow-sections header, .flow-order-link { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.flow-sections h3 { margin: 0; font-size: 15px; }.flow-sections p, .flow-order-link small { color: var(--workspace-field-muted); font-size: 12px; line-height: 1.7; }
.flow-order-link { margin-bottom: 8px; flex-wrap: wrap; }.flow-order-link + button { margin-top: 10px; }
@media (max-width: 1050px) { .flow-sections { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .flow-sections { grid-template-columns: 1fr; } }
</style>
