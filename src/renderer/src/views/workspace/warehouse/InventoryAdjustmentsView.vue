<script setup lang="ts">
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
import { NDatePicker, NModal } from 'naive-ui'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {datePickerString,vDateField} from '../../../utils/date-field'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import {signedAdjustmentMilli} from '../../../../../shared/adjustment-lot-api.ts'
import type {AdjustmentLotLineInput,AdjustmentLotOptions,AdjustmentLotPartInput} from '../../../../../shared/adjustment-lot-api'
import type {StockAdjustment} from '../../../../../shared/erp-api'

const store = usePiniaAppStore()
const { error, notice, user, busy, connectionLost, warehouses, materials, stockAdjustments,
  adjustmentForm, adjustmentDecisionReasons, adjustmentReversalReasons } = storeToRefs(store)
const { can, localTime, createStockAdjustment, submitStockAdjustment,
  approveStockAdjustment, rejectStockAdjustment, cancelStockAdjustment,
  loadAvailableAdjustmentLots, postStockAdjustment, reverseStockAdjustment } = store
const showForm = ref(false)
const query = ref('')
const filtered = computed(() => stockAdjustments.value.filter((item) =>
  [item.id, item.warehouse_name, item.reason, item.reference, ...item.lines.map((line) => line.material_name)]
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
  item.id === activeAdjustmentId.value && item.status === 'approved') ?? null)
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
        ><strong>#{{ item.id }}</strong
        ><small>{{ statusLabel[item.status] }}{{ item.reversal_id ? ' · 已冲销' : '' }}</small
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small v-if="item.reviewed_by_name">审批：{{ item.reviewed_by_name }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }}<small>{{ item.reason }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.review_reason">驳回：{{ item.review_reason }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} {{ line.quantity.startsWith('-') ? '' : '+'
          }}{{ line.quantity }} {{ line.unit }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="adjustment-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted'" class="adjustment-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('adjustment.submit')"
            :disabled="busy || connectionLost"
            @click="submitStockAdjustment(item.id)"
            variant="primary"
            size="small"
            type="button"
            >提交</AppButton
          >
          <AppButton
            v-if="
              item.status === 'submitted' &&
              can('adjustment.review') &&
              user?.id !== item.created_by
            "
            :disabled="busy || connectionLost"
            @click="approveStockAdjustment(item.id)"
            variant="primary"
            size="small"
            type="button"
            >批准</AppButton
          >
          <AppButton
            v-if="item.status === 'approved' && can('adjustment.post')"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
            type="button"
            >核对批次并仓库确认</AppButton
          >
          <AppButton
            v-if="
              ['draft', 'submitted', 'approved', 'rejected'].includes(item.status) &&
              can('adjustment.cancel')
            "
            :disabled="busy || connectionLost"
            @click="cancelStockAdjustment(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="
            item.status === 'submitted' && can('adjustment.review') && user?.id !== item.created_by
          "
          class="inline-form"
          @submit.prevent="rejectStockAdjustment(item.id)"
        >
          <label
            >驳回原因<AppInput
              v-model.trim="adjustmentDecisionReasons[item.id]"
              required
              maxlength="200" /></label
          ><AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >驳回</AppButton
          >
        </form>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('adjustment.reverse')"
          class="inline-form"
          @submit.prevent="reverseStockAdjustment(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="adjustmentReversalReasons[item.id]"
              required
              maxlength="200" /></label
          ><AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >冲销</AppButton
          >
        </form>
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small></template
      >
      <template #empty>{{ query ? '没有匹配的库存调整单。' : '暂无库存调整单。' }}</template>
    </WorkspaceTable>
    <NModal :show="!!activeAdjustment" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeAdjustment && can('adjustment.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>调整单 #{{ activeAdjustment.id }} · 实物批次归属</h2>
        <p>负向调整选择本仓实际减少的已有批次；正向调整可补入已有批次，或登记明确标为“调整新增”的新批次。只填写实物标签上可核对的来源批号与日期。</p>
        <p v-if="lotLoading">正在读取批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.adjustment_line_id" class="stack adjustment-lot-line">
          <h3>{{ activeAdjustment.lines.find(item=>item.id===line.adjustment_line_id)?.sku }} · 调整量 {{ activeAdjustment.lines.find(item=>item.id===line.adjustment_line_id)?.quantity }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="adjustment-lot-grid">
            <label>实物批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'选择批次',value:0,disabled:true},
                ...(milli(activeAdjustment?.lines.find(item=>item.id===line.adjustment_line_id)?.quantity ?? '0') > 0n
                  ? [{label:'登记调整新增批次',value:-1}] : []),
                ...(lotOptions?.lines.find(item=>item.adjustment_line_id===line.adjustment_line_id)?.lots ?? [])
                  .filter(lot=>milli(activeAdjustment?.lines.find(item=>item.id===line.adjustment_line_id)?.quantity ?? '0') > 0n
                    || (signedAdjustmentMilli(lot.quantity) ?? 0n) > 0n)
                  .map(lot=>({label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 本仓 ${lot.quantity}`,
                    value:lot.lot_id}))]" /></label>
            <label>批次数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <template v-if="part.lot_id === -1">
              <label>实物标签来源批号（可选）<AppInput v-model.trim="part.supplier_lot" maxlength="100" placeholder="未看到则留空" :disabled="busy" /></label>
              <label>生产日期（可选）<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body"
                type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
                :formatted-value="part.manufactured_on" :disabled="busy"
                @update:formatted-value="value=>part.manufactured_on=datePickerString(value)||null" /></label>
              <label>失效日期（可选）<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body"
                type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
                :formatted-value="part.expires_on" :disabled="busy"
                @update:formatted-value="value=>part.expires_on=datePickerString(value)||null" /></label>
            </template>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue && !lotLoading" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">仓库确认并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.adjustment-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.adjustment-lot-line h3{margin:0}
.adjustment-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.adjustment-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.adjustment-lot-grid{grid-template-columns:1fr}}
</style>
