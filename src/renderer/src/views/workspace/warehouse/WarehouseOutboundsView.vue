<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {outboundAvailableMilli} from '../../../../../shared/outbound-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {OutboundLotLineInput, OutboundLotOptions} from '../../../../../shared/outbound-lot-api'
import type {WarehouseOutbound} from '../../../../../shared/erp-api'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, materials, warehouses, warehouseOutbounds, otherOutboundForm,
  otherOutboundReversalReasons } = storeToRefs(store)
const { can, localTime, createOtherOutbound, loadAvailableOutboundLots, postWarehouseOutbound, cancelOtherOutbound,
  reverseOtherOutbound } = store
const showForm = ref(false)
const activeOutboundId = ref(0)
const lotOptions = ref<OutboundLotOptions | null>(null)
const lotDrafts = ref<OutboundLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeOutbound = computed(() => warehouseOutbounds.value.find(item =>
  item.id === activeOutboundId.value && item.status === 'draft') ?? null)
const query = ref('')
const filtered = computed(() => warehouseOutbounds.value.filter((item) =>
  [documentSearch(item), item.id, item.reference, item.warehouse_name, item.note, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const reasonName = { scrap: '报废', sample: '样品', other: '其他', purchase_return: '采购退货' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与来源' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createOtherOutbound, { busy, error, notice }, showForm)
}
function closeLotPost(): void {
  loadTicket++
  activeOutboundId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}
async function startLotPost(outbound: WarehouseOutbound): Promise<void> {
  const ticket = ++loadTicket
  activeOutboundId.value = outbound.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableOutboundLots(outbound.id)
    if (ticket !== loadTicket || activeOutboundId.value !== outbound.id) return
    if (result.warehouse_id !== outbound.warehouse_id
        || result.lines.length !== outbound.lines.length
        || result.lines.some(line => !outbound.lines.some(item =>
          item.id === line.outbound_line_id && item.material_id === line.material_id
          && item.quantity === line.quantity)))
      throw Error('可用批次与当前出库单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = outbound.lines.map(line => ({
      outbound_line_id: line.id, lots: [{lot_id: 0, quantity: line.quantity}]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}
function addLot(line: OutboundLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({lot_id: 0, quantity: ''})
}
const lotIssue = computed(() => {
  const outbound = activeOutbound.value, options = lotOptions.value
  if (!outbound || !options || lotDrafts.value.length !== outbound.lines.length)
    return '可用批次尚未读取。'
  for (const line of outbound.lines) {
    const draft = lotDrafts.value.find(item => item.outbound_line_id === line.id)
    const available = options.lines.find(item => item.outbound_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条出库明细至少指定一个实物批次。'
    const ids = new Set<number>()
    let total = 0n
    for (const part of draft.lots) {
      const candidate = available.lots.find(item => item.lot_id === part.lot_id)
      if (!candidate || ids.has(part.lot_id)) return `物料 ${line.sku} 的批次无效或重复。`
      ids.add(part.lot_id)
      const quantity = receiptLotMilli(part.quantity)
      if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      if (quantity > (outboundAvailableMilli(candidate.quantity) ?? 0n))
        return `批次 ${candidate.code} 的可用量不足，请重新读取。`
      total += quantity
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})
async function confirmLotPost(): Promise<void> {
  const outbound = activeOutbound.value
  if (!outbound || lotIssue.value || busy.value || connectionLost.value) return
  await postWarehouseOutbound(outbound.id, lotDrafts.value.map(line => ({
    outbound_line_id: line.outbound_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity}))})))
  if (!warehouseOutbounds.value.some(item => item.id === outbound.id && item.status === 'draft')) closeLotPost()
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="仓库出库"
      :columns="columns"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('other_outbound.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建仓库出库</AppButton
        >
      </template>
      <template #filters>
        <label>搜索出库单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label>
      </template>
      <template #beforeTable>
        <NModal
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="showForm && can('other_outbound.create')"
            class="stack"
            @submit.prevent="submitCreate"
          >
            <h3>其他用途出库</h3>
            <div class="form-grid">
              <label
                >仓库<WorkspaceSelect
                  v-model="otherOutboundForm.warehouse_id"
                  required
                  :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
              /></label>
              <label
                >用途<WorkspaceSelect
                  v-model="otherOutboundForm.reason"
                  required
                  :options="[
                    { label: '报废', value: 'scrap' },
                    { label: '样品', value: 'sample' },
                    { label: '其他', value: 'other' }
                  ]"
              /></label>
              <label
                >参考号<AppInput v-model.trim="otherOutboundForm.reference" maxlength="100"
              /></label>
              <label
                >出库说明<AppInput v-model.trim="otherOutboundForm.note" required maxlength="200"
              /></label>
            </div>
            <div v-for="(line, index) in otherOutboundForm.lines" :key="index" class="line-row">
              <label
                >物料<WorkspaceMaterialSelect :materials="materials"
                  v-model="line.material_id"
                  required
                  :options="[
                    { label: '选择物料', value: 0, disabled: true },
                    ...materials.map((item) => ({
                      label: (item.sku + ' · ' + item.name).trim(),
                      value: item.id
                    }))
                  ]"
              /></label>
              <label
                >数量<AppInput
                  v-model.trim="line.quantity"
                  type="number"
                  min="0.001"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <AppButton
                type="button"
                :disabled="otherOutboundForm.lines.length === 1"
                @click="otherOutboundForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                type="button"
                @click="otherOutboundForm.lines.push({ material_id: 0, quantity: '1' })"
                variant="secondary"
                >添加明细</AppButton
              >
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存草稿</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >收起</AppButton
              >
            </div>
            <p class="muted">确认后才扣减库存；其他出库不产生采购应付。</p>
          </form>
        </NModal>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>{{ documentLabel(item) }}</strong
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small>{{
          item.status === 'draft'
            ? '待确认'
            : item.status === 'cancelled'
              ? '已取消'
              : item.reversal_id
                ? '已冲销'
                : '已出库'
        }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }} · {{ reasonName[item.reason] }}<small>{{ item.note }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.purchase_return_id"
          >采购退货单 {{ relatedDocumentLabel(item, 'purchase_return') }}</small
        ></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="outbound-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted'" class="outbound-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('other_outbound.post')"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
            type="button"
            >指定批次并确认</AppButton
          >
          <AppButton
            v-if="
              item.status === 'draft' &&
              item.source_kind === 'other' &&
              can('other_outbound.cancel')
            "
            :disabled="busy || connectionLost"
            @click="cancelOtherOutbound(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="
            item.status === 'posted' &&
            !item.reversal_id &&
            item.source_kind === 'other' &&
            can('other_outbound.reverse')
          "
          class="inline-form"
          @submit.prevent="reverseOtherOutbound(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="otherOutboundReversalReasons[item.id]"
              required
              maxlength="200"
          /></label>
          <AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >冲销</AppButton
          >
        </form>
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small></template
      >
      <template #empty>{{ query ? '没有匹配的出库单。' : '暂无仓库出库单。' }}</template>
    </WorkspaceTable>
    <NModal :show="!!activeOutbound" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeOutbound && can('other_outbound.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>{{ activeOutbound.source_kind === 'purchase_return' ? '采购退货出库' : '其他出库' }} {{ documentLabel(activeOutbound) }} · 指定实物批次</h2>
        <p>从 {{ activeOutbound.warehouse_name }} 的实际可用批次逐行选择；历史未识别期初会明确标记，不能当作真实来料批号。</p>
        <p v-if="lotLoading">正在读取可用批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.outbound_line_id" class="stack outbound-lot-line">
          <h3>{{ activeOutbound.lines.find(item=>item.id===line.outbound_line_id)?.sku }} · {{ activeOutbound.lines.find(item=>item.id===line.outbound_line_id)?.material_name }} · {{ activeOutbound.lines.find(item=>item.id===line.outbound_line_id)?.quantity }} {{ activeOutbound.lines.find(item=>item.id===line.outbound_line_id)?.unit }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="outbound-lot-grid">
            <label>实物批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'选择批次',value:0,disabled:true},
                ...(lotOptions?.lines.find(item=>item.outbound_line_id===line.outbound_line_id)?.lots ?? []).map(lot=>({
                  label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
                  value:lot.lot_id}))]" /></label>
            <label>出库数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue && !lotLoading" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认出库并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.outbound-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.outbound-lot-line h3{margin:0}
.outbound-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.outbound-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.outbound-lot-grid{grid-template-columns:1fr}}
</style>
