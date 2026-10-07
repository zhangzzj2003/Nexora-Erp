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
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {outboundAvailableMilli} from '../../../../../shared/outbound-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {TransferLotLineInput, TransferLotOptions} from '../../../../../shared/transfer-lot-api'
import type {Transfer} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, materials, warehouses, transfers, transferForm, transferReversalReasons } = storeToRefs(store)
const { can, localTime, createTransfer, loadAvailableTransferLots, postTransfer, reverseTransfer } = store

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
  item.id === activeTransferId.value && item.status === 'draft' && item.approval?.status === 'approved') ?? null)

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
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const transferFormRows = computed(() => documentRows(transferForm.value.lines))
const transferFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
// 冲销原因从批准记录重新读取，临时输入不能替换已经审核的原因。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await store.openDocumentApproval({ document_type: 'Transfer', document_id: identifier, intent: 'reverse' })) return
  const record = store.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  transferReversalReasons.value[identifier] = record.reversal_reason
  store.closeDocumentApproval()
  await reverseTransfer(identifier)
}
const approvalLabels = { draft: '未送审', submitted: '审批中', approved: '已批准，待确认',
  rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }

</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('transfer.create')"
          v-model:show="createOpen"
          title="新建仓库调拨"
          :data="transferFormRows"
          :columns="transferFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost || warehouses.length < 2 || !materials.length"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="transferForm.lines.length >= 100"
          @add-material="transferForm.lines.push({ material_id: 0, quantity: '1' })"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >来源仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="transferForm.from_warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))]" /></label
            ><label
              >目标仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="transferForm.to_warehouse_id"
                required
                :options="[
                  { label: '选择目标仓库'.trim(), value: 0, disabled: true },
                  ...warehouses
                    .filter((entry) => entry.id !== transferForm.from_warehouse_id)
                    .map((item) => ({ label: item.name.trim(), value: item.id }))
                ]" /></label
            ><label
              >参考单号（可选）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="transferForm.reference"
                maxlength="100"
            /></label>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >物料<WorkspaceMaterialSelect
                :disabled="busy || connectionLost"
                :materials="materials"
                v-model="line.material_id"
                required
                :options="[
                  { label: '选择物料'.trim(), value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || transferForm.lines.length === 1"
              @click="transferForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
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
        <small v-if="item.status === 'draft'">{{ approvalLabels[item.approval?.status || 'draft'] }}</small>
        <small v-if="item.status !== 'draft' || item.reversal_id">{{
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
          <small v-else-if="item.status === 'posted'" class="transfer-lot-proof">普通调拨，未指定实物批次。</small>
        </div>
        <small v-if="item.reversal_id"
          >冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
          {{ localTime(item.reversed_at!) }}</small
        >
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton type="button" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'Transfer', document_id: item.id, intent: 'execute' })">单据审批</AppButton>
          <template v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('transfer.post')">
            <AppButton type="button" variant="primary" size="small" :disabled="busy || connectionLost" @click="postTransfer(item.id)">确认调拨</AppButton>
            <AppButton type="button" size="small" :disabled="busy || connectionLost" @click="startLotPost(item)">指定实物批次（可选）</AppButton>
          </template>

          <template v-if="item.status === 'posted' && !item.reversal_id && can('transfer.reverse')">
            <AppButton type="button" size="small" :disabled="busy || connectionLost"
              @click="store.openDocumentApproval({ document_type: 'Transfer', document_id: item.id, intent: 'reverse' })">冲销审批</AppButton>
            <AppButton v-if="item.reversal_approval?.status === 'approved'" type="button" size="small" :disabled="busy || connectionLost"
              @click="reverseApproved(item.id)">执行已批准冲销</AppButton>
          </template>
        </div>
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
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog v-if="activeTransfer && can('transfer.post')" :show="true"
      title="仓库调拨 · 批次选择" :document-number="documentLabel(activeTransfer)"
      :hint="'从 ' + activeTransfer.from_warehouse_name + ' 的实际可用批次逐行选择，批次编号随实物进入 ' + activeTransfer.to_warehouse_name + '。历史未识别期初不能当作真实来料批号。'"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="确认调拨"
      :loading="lotLoading" :load-error="lotLoadError"
      @update:show="value => { if (!value) closeLotPost() }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.transfer_line_id" :lots="line.lots"
        :sku="activeTransfer.lines.find(item => item.id === line.transfer_line_id)?.sku" :material-name="activeTransfer.lines.find(item => item.id === line.transfer_line_id)?.material_name"
        :unit="activeTransfer.lines.find(item => item.id === line.transfer_line_id)?.unit" :expected="activeTransfer.lines.find(item => item.id === line.transfer_line_id)?.quantity ?? ''"
        expected-label="应调拨" quantity-label="调拨数量" :selectable="true"
        :options="[{label:'选择批次',value:0,disabled:true},
                ...(lotOptions?.lines.find(item=>item.transfer_line_id===line.transfer_line_id)?.lots ?? []).map(lot=>({
                  label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
                  value:lot.lot_id}))]"
        :disabled="busy || connectionLost || lotLoading" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)" />
    </WorkspaceLotDialog>
    <DocumentApprovalDialog />
  </section>
</template>

<style scoped>
.transfer-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
</style>
