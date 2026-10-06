<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { computed, ref } from 'vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {outboundAvailableMilli} from '../../../../../shared/outbound-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {TransferLotLineInput, TransferLotOptions} from '../../../../../shared/transfer-lot-api'
import type {Transfer} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  warehouses,
  transfers,
  transferForm,
  transferReversalReasons,
  can,
  localTime,
  createTransfer,
  loadAvailableTransferLots,
  postTransfer,
  reverseTransfer
} = useAppStore()

// 搜索只过滤当前单据快照，不改动草稿、确认及冲销状态。
const query = ref('')
const filtered = computed(() => transfers.value.filter((item) =>
  [documentSearch(item), item.id, item.reference, item.from_warehouse_name, item.to_warehouse_name, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'document', title: '单据' }, { key: 'warehouse', title: '调拨仓库' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
const activeTransferId = ref(0)
const lotOptions = ref<TransferLotOptions | null>(null)
const lotDrafts = ref<TransferLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeTransfer = computed(() => transfers.value.find(item =>
  item.id === activeTransferId.value && item.status === 'draft') ?? null)

function closeLotPost(): void {
  loadTicket++
  activeTransferId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

async function startLotPost(transfer: Transfer): Promise<void> {
  const ticket = ++loadTicket
  activeTransferId.value = transfer.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableTransferLots(transfer.id)
    if (ticket !== loadTicket || activeTransferId.value !== transfer.id) return
    if (result.from_warehouse_id !== transfer.from_warehouse_id
        || result.to_warehouse_id !== transfer.to_warehouse_id
        || result.lines.length !== transfer.lines.length
        || result.lines.some(line => !transfer.lines.some(item =>
          item.id === line.transfer_line_id && item.material_id === line.material_id
          && item.quantity === line.quantity)))
      throw Error('可用批次与当前调拨单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = transfer.lines.map(line => ({
      transfer_line_id: line.id, lots: [{lot_id: 0, quantity: line.quantity}]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: TransferLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({lot_id: 0, quantity: ''})
}

const lotIssue = computed(() => {
  const transfer = activeTransfer.value, options = lotOptions.value
  if (!transfer || !options || lotDrafts.value.length !== transfer.lines.length)
    return '可用批次尚未读取。'
  for (const line of transfer.lines) {
    const draft = lotDrafts.value.find(item => item.transfer_line_id === line.id)
    const available = options.lines.find(item => item.transfer_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条调拨明细至少指定一个实物批次。'
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
  const transfer = activeTransfer.value
  if (!transfer || lotIssue.value || busy.value || connectionLost.value) return
  await postTransfer(transfer.id, lotDrafts.value.map(line => ({
    transfer_line_id: line.transfer_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity}))})))
  if (!transfers.value.some(item => item.id === transfer.id && item.status === 'draft')) closeLotPost()
}
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createTransfer, { busy, error, notice }, createOpen)
}
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('transfer.create')"
      v-model:show="createOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">WAREHOUSE TRANSFER</p>
          <h2>新建调拨单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >来源仓库<WorkspaceSelect
              v-model="transferForm.from_warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >目标仓库<WorkspaceSelect
              v-model="transferForm.to_warehouse_id"
              required
              :options="[
                { label: '选择目标仓库'.trim(), value: 0, disabled: true },
                ...warehouses
                  .filter((entry) => entry.id !== transferForm.from_warehouse_id)
                  .map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >参考单号（可选）<AppInput v-model.trim="transferForm.reference" maxlength="100"
          /></label>
        </div>
        <h3>调拨明细</h3>
        <div v-for="(line, index) in transferForm.lines" :key="index" class="line-row">
          <label
            >物料<WorkspaceMaterialSelect :materials="materials"
              v-model="line.material_id"
              required
              :options="[
                { label: '选择物料'.trim(), value: 0, disabled: true },
                ...materials.map((item) => ({
                  label: (item.sku + ' · ' + item.name).trim(),
                  value: item.id
                }))
              ]" /></label
          ><label
            >数量<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="transferForm.lines.length === 1"
            @click="transferForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="transferForm.lines.push({ material_id: 0, quantity: '1' })"
            variant="secondary"
          >
            添加明细</AppButton
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost || warehouses.length < 2 || !materials.length"
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 单据列表与台账共用表格，原有权限检查和冲销明细完整保留。 -->
    <WorkspaceTable
      :show-title="false"
      title="仓库调拨"
      :columns="columns"
      :data="filtered"
      :min-table-width="1050"
    >
      <template #actions>
        <AppButton
          v-if="can('transfer.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click="createOpen = true"
          variant="primary"
          >新建调拨单</AppButton
        >
      </template>
      <template #filters
        ><label>搜索调拨单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label
      ></template>
      <template #cell-document="{ row: item }">
        <strong>{{ documentLabel(item) }}</strong>
        <small>{{
          item.reversal_id ? '已冲销' : item.status === 'posted' ? '已调拨' : '待确认'
        }}</small>
        <small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small>
        <small v-if="item.reference">{{ item.reference }}</small>
      </template>
      <template #cell-warehouse="{ row: item }"
        >{{ item.from_warehouse_name }} → {{ item.to_warehouse_name }}</template
      >
      <template #cell-lines="{ row: item }">
        <div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="transfer-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted'" class="transfer-lot-proof">旧确认未指定实物批次，两个仓库的数量在批次核对页显示为差额。</small>
        </div>
        <small v-if="item.reversal_id"
          >冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
          {{ localTime(item.reversed_at!) }}</small
        >
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('transfer.post')"
            type="button"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            指定批次并确认
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('transfer.reverse')"
          class="inline-form"
          @submit.prevent="reverseTransfer(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="transferReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原调拨为何需要冲销" /></label
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
          >
            冲销已确认调拨
          </AppButton>
        </form>
      </template>
      <template #empty>
        <strong>{{ query ? '没有匹配的单据' : '暂无调拨单' }}</strong>
        <span>{{
          query
            ? '可调整单号、仓库或物料关键词后重新搜索。'
            : '保存新建单据后，可在这里查看明细与处理状态。'
        }}</span>
      </template>
    </WorkspaceTable>
    <NModal :show="!!activeTransfer" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeTransfer && can('transfer.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>调拨单 {{ documentLabel(activeTransfer) }} · 指定实物批次</h2>
        <p>从 {{ activeTransfer.from_warehouse_name }} 的实际可用批次逐行选择，批次编号随实物进入 {{ activeTransfer.to_warehouse_name }}。历史未识别期初不能当作真实来料批号。</p>
        <p v-if="lotLoading">正在读取可用批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.transfer_line_id" class="stack transfer-lot-line">
          <h3>{{ activeTransfer.lines.find(item=>item.id===line.transfer_line_id)?.sku }} · {{ activeTransfer.lines.find(item=>item.id===line.transfer_line_id)?.material_name }} · {{ activeTransfer.lines.find(item=>item.id===line.transfer_line_id)?.quantity }} {{ activeTransfer.lines.find(item=>item.id===line.transfer_line_id)?.unit }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="transfer-lot-grid">
            <label>实物批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'选择批次',value:0,disabled:true},
                ...(lotOptions?.lines.find(item=>item.transfer_line_id===line.transfer_line_id)?.lots ?? []).map(lot=>({
                  label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
                  value:lot.lot_id}))]" /></label>
            <label>调拨数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue && !lotLoading" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认调拨并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.transfer-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.transfer-lot-line h3{margin:0}
.transfer-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.transfer-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.transfer-lot-grid{grid-template-columns:1fr}}
</style>
