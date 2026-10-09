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
import { storeToRefs } from 'pinia'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import {signedAdjustmentMilli} from '../../../../../shared/adjustment-lot-api.ts'
import type {AdjustmentLotLineInput,AdjustmentLotOptions,AdjustmentLotPartInput} from '../../../../../shared/adjustment-lot-api'
import type {StockAdjustment} from '../../../../../shared/erp-api'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, warehouses, materials, stockAdjustments,
  adjustmentForm, adjustmentReversalReasons } = storeToRefs(store)
const { can, localTime, createStockAdjustment, cancelStockAdjustment,
  loadAvailableAdjustmentLots, postStockAdjustment, reverseStockAdjustment } = store
const showForm = ref(false)
const query = ref('')
const filtered = computed(() => stockAdjustments.value.filter((item) =>
  [documentSearch(item), item.id, item.warehouse_name, item.reason, item.reference, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const statusLabel = { draft: '草稿', submitted: '待审批', approved: '待仓库确认',
  rejected: '已驳回', cancelled: '已取消', posted: '已确认' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与原因' },
  { key: 'lines', title: '调整明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createStockAdjustment, { busy, error, notice }, showForm)
}

const activeAdjustmentId = ref(0)
const lotOptions = ref<AdjustmentLotOptions | null>(null)
const lotDrafts = ref<AdjustmentLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeAdjustment = computed(() => stockAdjustments.value.find(item =>
  item.id === activeAdjustmentId.value && item.status === 'approved' && item.approval?.status === 'approved') ?? null)
const milli = (value: string): bigint => signedAdjustmentMilli(value) ?? 0n

function closeLotPost(): void {
  loadTicket++
  activeAdjustmentId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

function newPart(quantity: string, signed: bigint): AdjustmentLotPartInput {
  return {lot_id: signed > 0n ? -1 : 0, quantity,
    supplier_lot: null, manufactured_on: null, expires_on: null}
}

async function startLotPost(adjustment: StockAdjustment): Promise<void> {
  const ticket = ++loadTicket
  activeAdjustmentId.value = adjustment.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableAdjustmentLots(adjustment.id)
    if (ticket !== loadTicket || activeAdjustmentId.value !== adjustment.id) return
    if (result.warehouse_id !== adjustment.warehouse_id
        || result.lines.length !== adjustment.lines.length
        || result.lines.some(line => !adjustment.lines.some(item =>
          item.id === line.adjustment_line_id && item.material_id === line.material_id
          && milli(item.quantity) === milli(line.quantity))))
      throw Error('可用批次与当前调整单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = adjustment.lines.map(line => ({adjustment_line_id: line.id,
      lots: [newPart(line.quantity.replace('-', ''), milli(line.quantity))]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: AdjustmentLotLineInput): void {
  if (line.lots.length < 20) line.lots.push(newPart('', milli(
    activeAdjustment.value?.lines.find(item => item.id === line.adjustment_line_id)?.quantity ?? '0')))
}

const lotIssue = computed(() => {
  const adjustment = activeAdjustment.value, options = lotOptions.value
  if (!adjustment || !options) return '可用批次尚未读取。'
  if (lotDrafts.value.length !== adjustment.lines.length) return '调整批次明细不完整。'
  for (const line of adjustment.lines) {
    const draft = lotDrafts.value.find(item => item.adjustment_line_id === line.id)
    const available = options.lines.find(item => item.adjustment_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条调整明细至少指定一个实物批次。'
    const signed = milli(line.quantity)
    const ids = new Set<number>()
    let total = 0n
    for (const part of draft.lots) {
      const quantity = receiptLotMilli(part.quantity)
      if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      if (part.lot_id === -1 && signed > 0n) {
        if (part.supplier_lot && part.supplier_lot.length > 100)
          return '来源批号不能超过 100 字。'
        if ((part.manufactured_on && !receiptLotDate(part.manufactured_on))
            || (part.expires_on && !receiptLotDate(part.expires_on))
            || (part.manufactured_on && part.expires_on
                && part.expires_on < part.manufactured_on))
          return '调整新增批次的日期无效。'
      } else {
        const candidate = available.lots.find(item => item.lot_id === part.lot_id)
        if (!candidate || ids.has(part.lot_id ?? 0)) return `物料 ${line.sku} 的批次无效或重复。`
        ids.add(part.lot_id!)
        if (signed < 0n && quantity > (signedAdjustmentMilli(candidate.quantity) ?? 0n))
          return `批次 ${candidate.code} 的本仓余量不足，请重新读取。`
      }
      total += quantity
    }
    if (total !== (signed < 0n ? -signed : signed))
      return `物料 ${line.sku} 的批次数量之和须等于调整量 ${line.quantity} 的绝对值。`
  }
  return ''
})

async function confirmLotPost(): Promise<void> {
  const adjustment = activeAdjustment.value
  if (!adjustment || lotIssue.value || busy.value || connectionLost.value) return
  const lines = lotDrafts.value.map(line => ({adjustment_line_id: line.adjustment_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id === -1 ? null : part.lot_id,
      quantity: part.quantity,
      supplier_lot: part.lot_id === -1 ? part.supplier_lot?.trim() || null : null,
      manufactured_on: part.lot_id === -1 ? part.manufactured_on || null : null,
      expires_on: part.lot_id === -1 ? part.expires_on || null : null}))}))
  await postStockAdjustment(adjustment.id, lines)
  if (!stockAdjustments.value.some(item => item.id === adjustment.id && item.status === 'approved'))
    closeLotPost()
}
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const adjustmentFormRows = computed(() => documentRows(adjustmentForm.value.lines))
const adjustmentFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '调整量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
// 冲销原因从批准记录重新读取，临时输入不能替换已经审核的原因。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await store.openDocumentApproval({ document_type: 'StockAdjustment', document_id: identifier, intent: 'reverse' })) return
  const record = store.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  adjustmentReversalReasons.value[identifier] = record.reversal_reason
  store.closeDocumentApproval()
  await reverseStockAdjustment(identifier)
}
const approvalLabels = { draft: '未送审', submitted: '审批中', approved: '已批准，待确认',
  rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }

</script>

<template>
  <section class="stack">
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="库存调整"
      :columns="columns"
      :min-table-width="1050"
    >
      <template #actions>
        <AppButton
          v-if="can('adjustment.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建调整</AppButton
        >
      </template>
      <template #filters
        ><label>搜索调整单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label
      ></template>
      <template #beforeTable>
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          material-supply
          v-if="showForm && can('adjustment.create')"
          v-model:show="showForm"
          title="新建库存调整"
          :data="adjustmentFormRows"
          :columns="adjustmentFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="adjustmentForm.lines.length >= 100"
          @add-material="adjustmentForm.lines.push({ material_id: 0, quantity: '1' })"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="adjustmentForm.warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
            /></label>
            <label
              >调整原因<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="adjustmentForm.reason"
                required
                maxlength="200"
            /></label>
            <label
              >参考号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="adjustmentForm.reference"
                maxlength="100"
            /></label>

            <div class="document-basic-extra">
              <p class="muted">正数为增加，负数为减少；零调整量不会保存。</p>
            </div></template
          >
          <template #cell-material="{ row: { line, index } }"
            ><label
              >物料<WorkspaceMaterialSelect
                :disabled="busy || connectionLost"
                :materials="materials"
                v-model="line.material_id"
                required
                :options="[
                  { label: '选择物料', value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >调整量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="-1000000"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || adjustmentForm.lines.length === 1"
              @click="adjustmentForm.lines.splice(index, 1)"
              variant="text"
              >移除</AppButton
            ></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>{{ documentLabel(item) }}</strong
        ><small>{{ ['posted', 'cancelled'].includes(item.status) ? statusLabel[item.status] : approvalLabels[item.approval?.status || 'draft'] }}{{ item.reversal_id ? ' · 已冲销' : '' }}</small
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small v-if="item.reviewed_by_name">{{ item.approval?.version ? '最近审核' : '升级前审核' }}：{{ item.reviewed_by_name }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }}<small>{{ item.reason }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.review_reason">{{ item.status === 'rejected' ? '驳回原因' : '审核意见' }}：{{ item.review_reason }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} {{ line.quantity.startsWith('-') ? '' : '+'
          }}{{ line.quantity }} {{ line.unit }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="adjustment-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted'" class="adjustment-lot-proof">普通确认，未指定实物批次。</small>
        </div></template
      >
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton type="button" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'StockAdjustment', document_id: item.id, intent: 'execute' })">单据审批</AppButton>
          <template v-if="item.status === 'approved' && item.approval?.status === 'approved' && can('adjustment.post')">
            <AppButton type="button" variant="primary" size="small" :disabled="busy || connectionLost" @click="postStockAdjustment(item.id)">仓库确认</AppButton>
            <AppButton type="button" size="small" :disabled="busy || connectionLost" @click="startLotPost(item)">指定实物批次（可选）</AppButton>
          </template>
          <AppButton v-if="['draft', 'submitted', 'approved', 'rejected'].includes(item.status) && !['submitted', 'approved'].includes(item.approval?.status || '') && can('adjustment.cancel')"
            type="button" size="small" :disabled="busy || connectionLost" @click="cancelStockAdjustment(item.id)">取消</AppButton>
          <template v-if="item.status === 'posted' && !item.reversal_id && can('adjustment.reverse')">
            <AppButton type="button" size="small" :disabled="busy || connectionLost"
              @click="store.openDocumentApproval({ document_type: 'StockAdjustment', document_id: item.id, intent: 'reverse' })">冲销审批</AppButton>
            <AppButton v-if="item.reversal_approval?.status === 'approved'" type="button" size="small" :disabled="busy || connectionLost"
              @click="reverseApproved(item.id)">执行已批准冲销</AppButton>
          </template>
        </div>
      </template>
      <template #empty>{{ query ? '没有匹配的库存调整单。' : '暂无库存调整单。' }}</template>
    </WorkspaceTable>
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog v-if="activeAdjustment && can('adjustment.post')" :show="true"
      title="库存调整 · 批次归属" :document-number="documentLabel(activeAdjustment)"
      hint="负向调整选择本仓实际减少的已有批次；正向调整可补入已有批次，或登记明确标为“调整新增”的新批次。只填写实物标签上可核对的来源批号与日期。"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="仓库确认"
      :loading="lotLoading" :load-error="lotLoadError"
      @update:show="value => { if (!value) closeLotPost() }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.adjustment_line_id" :lots="line.lots"
        :sku="activeAdjustment.lines.find(item => item.id === line.adjustment_line_id)?.sku" :material-name="activeAdjustment.lines.find(item => item.id === line.adjustment_line_id)?.material_name"
        :unit="activeAdjustment.lines.find(item => item.id === line.adjustment_line_id)?.unit" :expected="activeAdjustment.lines.find(item => item.id === line.adjustment_line_id)?.quantity ?? ''"
        :expected-label="milli(activeAdjustment.lines.find(item => item.id === line.adjustment_line_id)?.quantity ?? '0') > 0n ? '调增应分配' : '调减应分配'" quantity-label="批次数量" :selectable="true" :new-lot-value="-1"
        :options="[{label:'选择批次',value:0,disabled:true},
                ...(milli(activeAdjustment?.lines.find(item=>item.id===line.adjustment_line_id)?.quantity ?? '0') > 0n
                  ? [{label:'登记调整新增批次',value:-1}] : []),
                ...(lotOptions?.lines.find(item=>item.adjustment_line_id===line.adjustment_line_id)?.lots ?? [])
                  .filter(lot=>milli(activeAdjustment?.lines.find(item=>item.id===line.adjustment_line_id)?.quantity ?? '0') > 0n
                    || (signedAdjustmentMilli(lot.quantity) ?? 0n) > 0n)
                  .map(lot=>({label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 本仓 ${lot.quantity}`,
                    value:lot.lot_id}))]"
        :disabled="busy || connectionLost || lotLoading" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)" />
    </WorkspaceLotDialog>
    <DocumentApprovalDialog />
  </section>
</template>

<style scoped>
.adjustment-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
</style>
