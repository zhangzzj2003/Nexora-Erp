<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker, NModal } from 'naive-ui'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {datePickerString,vDateField} from '../../../utils/date-field'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {SalesReturnLotLineInput,SalesReturnLotOptions,SalesReturnLotPartInput} from '../../../../../shared/sales-return-lot-api'
import type {SalesReturn} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const {
  error,
  notice,
  busy,
  connectionLost,
  warehouses,
  shipments,
  salesReturns,
  salesReturnReversalReasons,
  salesReturnForm,
  selectedSalesReturnShipment
} = storeToRefs(store)
const {
  can,
  localTime,
  chooseSalesReturnShipment,
  createSalesReturn,
  loadAvailableSalesReturnLots,
  postSalesReturn,
  cancelSalesReturn,
  reverseSalesReturn
} = store

const activeReturnId = ref(0)
const lotOptions = ref<SalesReturnLotOptions | null>(null)
const lotDrafts = ref<SalesReturnLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeReturn = computed(() => salesReturns.value.find(item =>
  item.id === activeReturnId.value && item.status === 'draft') ?? null)

function closeLotPost(): void {
  loadTicket++
  activeReturnId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

function newPart(quantity: string): SalesReturnLotPartInput {
  return {lot_id: null, quantity, supplier_lot: null, manufactured_on: null, expires_on: null}
}

async function startLotPost(saleReturn: SalesReturn): Promise<void> {
  const ticket = ++loadTicket
  activeReturnId.value = saleReturn.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableSalesReturnLots(saleReturn.id)
    if (ticket !== loadTicket || activeReturnId.value !== saleReturn.id) return
    if (result.shipment_id !== saleReturn.shipment_id
        || result.warehouse_id !== saleReturn.warehouse_id
        || result.lines.length !== saleReturn.lines.length
        || result.lines.some(line => !saleReturn.lines.some(item =>
          item.id === line.return_line_id && item.shipment_line_id === line.shipment_line_id
          && item.material_id === line.material_id && item.quantity === line.quantity)))
      throw Error('原出库批次与当前销售退货单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = saleReturn.lines.map(line => ({return_line_id: line.id,
      lots: [newPart(line.quantity)]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: SalesReturnLotLineInput): void {
  if (line.lots.length < 20) line.lots.push(newPart(''))
}

const lotIssue = computed(() => {
  const saleReturn = activeReturn.value, options = lotOptions.value
  if (!saleReturn || !options || lotDrafts.value.length !== saleReturn.lines.length)
    return '原出库批次尚未读取。'
  for (const line of saleReturn.lines) {
    const draft = lotDrafts.value.find(item => item.return_line_id === line.id)
    const available = options.lines.find(item => item.return_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条退货明细至少指定一个回仓实物批次。'
    const ids = new Set<number>()
    let total = 0n
    for (const part of draft.lots) {
      const quantity = receiptLotMilli(part.quantity)
      if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      if (part.lot_id === null) {
        if (part.supplier_lot && part.supplier_lot.length > 100)
          return '来源批号不能超过 100 字。'
        if ((part.manufactured_on && !receiptLotDate(part.manufactured_on))
            || (part.expires_on && !receiptLotDate(part.expires_on))
            || (part.manufactured_on && part.expires_on
                && part.expires_on < part.manufactured_on))
          return '退回新批次的日期无效。'
      } else {
        const candidate = available.lots.find(item => item.lot_id === part.lot_id)
        if (!candidate || ids.has(part.lot_id)) return `物料 ${line.sku} 的原出库批次无效或重复。`
        ids.add(part.lot_id)
        if (quantity > (receiptLotMilli(candidate.quantity) ?? 0n))
          return `原出库批次 ${candidate.code} 的剩余可退量不足，请重新读取。`
      }
      total += quantity
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的回仓批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})

async function confirmLotPost(): Promise<void> {
  const saleReturn = activeReturn.value
  if (!saleReturn || lotIssue.value || busy.value || connectionLost.value) return
  await postSalesReturn(saleReturn.id, lotDrafts.value.map(line => ({
    return_line_id: line.return_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity,
      supplier_lot: part.lot_id === null ? part.supplier_lot?.trim() || null : null,
      manufactured_on: part.lot_id === null ? part.manufactured_on : null,
      expires_on: part.lot_id === null ? part.expires_on : null}))})))
  if (!salesReturns.value.some(item => item.id === saleReturn.id && item.status === 'draft'))
    closeLotPost()
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createSalesReturn, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  salesReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.customer_name,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const salesReturnFormRows = computed(() => documentRows(salesReturnForm.value.lines))
const salesReturnFormColumns = [
  { key: 'material', title: '原出库物料', width: '300' },
  { key: 'quantity', title: '退货数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('sales_return.create')"
          v-model:show="createOpen"
          title="新建销售退货单"
          :data="salesReturnFormRows"
          :columns="salesReturnFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!salesReturnForm.lines.length || !warehouses.length"
          submit-label="保存草稿"
          :min-table-width="800"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >原出库单<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="salesReturnForm.shipment_id"
                required
                @change="chooseSalesReturnShipment"
                :options="[
                  { label: '选择可退货的出库单', value: 0, disabled: true },
                  ...shipments
                    .filter(
                      (entry) =>
                        entry.status === 'posted' &&
                        entry.lines.some((line) => Number(line.returnable_quantity) > 0)
                    )
                    .map((item) => ({
                      label: (' #' + item.id + ' · ' + item.customer_name + ' · ' + item.warehouse_name).trim(),
                      value: item.id
                    }))
                ]" /></label
            ><label
              >退回仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="salesReturnForm.warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]" /></label
            ><label
              >退货原因<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="salesReturnForm.reason"
                required
                maxlength="200"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">
                退货关联原出库明细；确认后新增入库流水，不修改原出库记录。金额按原销售单价计算，应收调整将在财务模块处理。
              </p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >原出库物料<AppInput
                :model-value="
                  selectedSalesReturnShipment?.lines.find((item) => item.id === line.shipment_line_id)
                    ?.material_name
                "
                disabled /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >退货数量（最多
              {{
                selectedSalesReturnShipment?.lines.find((item) => item.id === line.shipment_line_id)
                  ?.returnable_quantity
              }}）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
                :max="
                  selectedSalesReturnShipment?.lines.find((item) => item.id === line.shipment_line_id)
                    ?.returnable_quantity
                "
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              :disabled="busy || connectionLost"
              type="button"
              @click="salesReturnForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="销售退货"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('sales_return.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建销售退货单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索销售退货
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>#{{ item.id }} · {{ item.customer_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 原出库单 #{{ item.shipment_id }} ·
            {{ item.reason }} · 创建人 {{ item.created_by_name }} · 原价金额 ¥{{
              item.total_amount
            }}
            <span v-if="item.reversal_id">
              · 冲销 #{{ item.reversal_id }}（{{ item.reversal_reason }} ·
              {{ item.reversed_by_name }}）
            </span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            item.reversal_id
              ? '已冲销'
              : item.status === 'posted'
                ? '已退货入库'
                : item.status === 'cancelled'
                  ? '已取消'
                  : '待确认'
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }} · ¥{{ line.line_total }}
            <small v-if="item.status === 'posted' && line.physical_lots?.length" class="return-lot-proof">
              实物批次：{{ line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
            </small>
            <small v-else-if="item.status === 'posted'" class="return-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('sales_return.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            核对批次并确认退货
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('sales_return.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelSalesReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('sales_return.reverse')"
          class="inline-form"
          @submit.prevent="reverseSalesReturn(item.id)"
        >
          <label>
            冲销原因
            <AppInput
              v-model.trim="salesReturnReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原退货为何需要冲销"
            />
          </label>
          <AppButton type="submit" :disabled="busy" variant="secondary" size="small"
            >冲销已确认退货</AppButton
          >
        </form>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无销售退货记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
    <NModal :show="!!activeReturn" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeReturn && can('sales_return.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>销售退货 #{{ activeReturn.id }} · 回仓实物批次</h2>
        <p>可归回原出库已记录的批次，数量不得超过该批次剩余可退量；实物不属于原批次或原出库未记录批次时，登记“退货新批次”。退回仓库为 {{ activeReturn.warehouse_name }}。</p>
        <p v-if="lotLoading">正在读取原出库批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.return_line_id" class="stack return-lot-line">
          <h3>{{ activeReturn.lines.find(item=>item.id===line.return_line_id)?.sku }} · 退货量 {{ activeReturn.lines.find(item=>item.id===line.return_line_id)?.quantity }}</h3>
          <p v-if="!lotOptions?.lines.find(item=>item.return_line_id===line.return_line_id)?.lots.length" class="muted">原出库未登记可退批次，须登记退货新批次；旧单据仍可在批次核对页追踪差额。</p>
          <div v-for="(part,index) in line.lots" :key="index" class="return-lot-grid">
            <label>回仓批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'登记退货新批次',value:null},
                ...(lotOptions?.lines.find(item=>item.return_line_id===line.return_line_id)?.lots ?? [])
                  .map(lot=>({label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 剩余可退 ${lot.quantity}`,
                    value:lot.lot_id}))]" /></label>
            <label>批次数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <template v-if="part.lot_id === null">
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
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认退货并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.return-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.return-lot-line h3{margin:0}
.return-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.return-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.return-lot-grid{grid-template-columns:1fr}}
</style>
