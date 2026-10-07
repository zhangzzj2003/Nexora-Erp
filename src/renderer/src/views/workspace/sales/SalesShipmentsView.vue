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
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {outboundAvailableMilli} from '../../../../../shared/outbound-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {ShipmentLotLineInput,ShipmentLotOptions} from '../../../../../shared/shipment-lot-api'
import type {Shipment} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  warehouses,
  salesOrders,
  shipments,
  shipmentReversalReasons,
  shipmentForm,
  can,
  localTime,
  chooseShipmentOrder,
  createShipment,
  loadAvailableShipmentLots,
  postShipment,
  cancelShipment,
  reverseShipment
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
const activeShipmentId = ref(0)
const lotOptions = ref<ShipmentLotOptions | null>(null)
const lotDrafts = ref<ShipmentLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeShipment = computed(() => shipments.value.find(item =>
  item.id === activeShipmentId.value && item.status === 'draft') ?? null)

function closeLotPost(): void {
  loadTicket++
  activeShipmentId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

async function startLotPost(shipment: Shipment): Promise<void> {
  const ticket = ++loadTicket
  activeShipmentId.value = shipment.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableShipmentLots(shipment.id)
    if (ticket !== loadTicket || activeShipmentId.value !== shipment.id) return
    if (result.warehouse_id !== shipment.warehouse_id
        || result.lines.length !== shipment.lines.length
        || result.lines.some(line => !shipment.lines.some(item =>
          item.id === line.shipment_line_id && item.material_id === line.material_id
          && item.quantity === line.quantity)))
      throw Error('可用批次与当前销售出库单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = shipment.lines.map(line => ({
      shipment_line_id: line.id, lots: [{lot_id: 0, quantity: line.quantity}]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: ShipmentLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({lot_id: 0, quantity: ''})
}

const lotIssue = computed(() => {
  const shipment = activeShipment.value, options = lotOptions.value
  if (!shipment || !options || lotDrafts.value.length !== shipment.lines.length)
    return '可用批次尚未读取。'
  for (const line of shipment.lines) {
    const draft = lotDrafts.value.find(item => item.shipment_line_id === line.id)
    const available = options.lines.find(item => item.shipment_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条销售出库明细至少指定一个实物批次。'
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
  const shipment = activeShipment.value
  if (!shipment || lotIssue.value || busy.value || connectionLost.value) return
  await postShipment(shipment.id, lotDrafts.value.map(line => ({
    shipment_line_id: line.shipment_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity}))})))
  if (!shipments.value.some(item => item.id === shipment.id && item.status === 'draft')) closeLotPost()
}
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createShipment, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  shipments.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.customer_name,
      item.warehouse_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const shipmentFormRows = computed(() => documentRows(shipmentForm.value.lines))
const shipmentFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '出库数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('shipment.create')"
          v-model:show="createOpen"
          title="新建销售出库"
          :data="shipmentFormRows"
          :columns="shipmentFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="
            busy ||
            !materials.length ||
            !salesOrders.some((entry) => ['confirmed', 'partially_shipped'].includes(entry.status))
          "
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="shipmentForm.lines.length >= 100"
          @add-material="shipmentForm.lines.push({ material_id: 0, quantity: '1' })"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >销售订单<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="shipmentForm.sales_order_id"
                required
                @change="chooseShipmentOrder"
                :options="[
                  { label: '选择待出库订单'.trim(), value: 0, disabled: true },
                  ...salesOrders
                    .filter((entry) => ['confirmed', 'partially_shipped'].includes(entry.status))
                    .map((item) => ({
                      label: (' #' + item.id + ' · ' + item.customer_name).trim(),
                      value: item.id
                    }))
                ]" /></label
            ><label
              >出库仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="shipmentForm.warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))]" /></label
            ><label
              >参考单号（可选）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="shipmentForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">确认出库时将从所选仓库扣减库存，并再次核对销售订单剩余数量。</p>
            </div>
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
              >出库数量<AppInput
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
              :disabled="busy || connectionLost || shipmentForm.lines.length === 1"
              @click="shipmentForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="销售出库"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('shipment.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建出库单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索销售出库
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ item.customer_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 销售订单 {{ relatedDocumentLabel(item, 'sales_order') }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
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
                ? '已出库'
                : item.status === 'cancelled'
                  ? '已取消'
                  : '待确认'
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }} · 已退
            {{ line.returned_quantity }} · 可退 {{ line.returnable_quantity }}
            <small v-if="item.status === 'posted' && line.physical_lots?.length" class="shipment-lot-proof">
              实物批次：{{ line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
            </small>
            <small v-else-if="item.status === 'posted'" class="shipment-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('shipment.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            指定批次并确认
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('shipment.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelShipment(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('shipment.reverse')"
          class="inline-form"
          @submit.prevent="reverseShipment(item.id)"
        >
          <label>
            冲销原因
            <AppInput
              v-model.trim="shipmentReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原出库为何需要冲销"
            />
          </label>
          <AppButton type="submit" :disabled="busy" variant="secondary" size="small"
            >冲销已确认出库</AppButton
          >
        </form>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无销售出库记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog v-if="activeShipment && can('shipment.post')" :show="true"
      title="销售出库 · 批次选择" :document-number="documentLabel(activeShipment)"
      :hint="'从 ' + activeShipment.warehouse_name + ' 的实际可用批次逐行选择；历史未识别期初会明确标记，不能当作真实来料批号。'"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="确认出库"
      :loading="lotLoading" :load-error="lotLoadError"
      @update:show="value => { if (!value) closeLotPost() }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.shipment_line_id" :lots="line.lots"
        :sku="activeShipment.lines.find(item => item.id === line.shipment_line_id)?.sku" :material-name="activeShipment.lines.find(item => item.id === line.shipment_line_id)?.material_name"
        :unit="activeShipment.lines.find(item => item.id === line.shipment_line_id)?.unit" :expected="activeShipment.lines.find(item => item.id === line.shipment_line_id)?.quantity ?? ''"
        expected-label="应出库" quantity-label="出库数量" :selectable="true"
        :options="[{label:'选择批次',value:0,disabled:true},
                ...(lotOptions?.lines.find(item=>item.shipment_line_id===line.shipment_line_id)?.lots ?? []).map(lot=>({
                  label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
                  value:lot.lot_id}))]"
        :disabled="busy || connectionLost || lotLoading" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)" />
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped>
.shipment-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
</style>
