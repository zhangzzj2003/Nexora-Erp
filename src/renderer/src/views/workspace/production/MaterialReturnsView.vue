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
import type {MaterialReturnLotLineInput,MaterialReturnLotOptions,MaterialReturnLotPartInput} from '../../../../../shared/material-return-lot-api'
import type {MaterialReturn} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const {
  error,
  notice,
  busy,
  connectionLost,
  workOrders,
  materialIssues,
  materialReturns,
  materialReturnForm,
  selectedReturnIssue,
} = storeToRefs(store)
const {
  can,
  localTime,
  selectReturnIssue,
  createMaterialReturn,
  loadAvailableMaterialReturnLots,
  postMaterialReturn,
  cancelMaterialReturn,
  reverseMaterialReturn
} = store

const activeReturnId = ref(0)
const lotOptions = ref<MaterialReturnLotOptions | null>(null)
const lotDrafts = ref<MaterialReturnLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
const reversalReasons = ref<Record<number, string>>({})
let loadTicket = 0
const activeReturn = computed(() => materialReturns.value.find(item =>
  item.id === activeReturnId.value && item.status === 'draft') ?? null)

function closeLotPost(): void {
  loadTicket++
  activeReturnId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

function newPart(quantity: string): MaterialReturnLotPartInput {
  return {lot_id: null, quantity, supplier_lot: null, manufactured_on: null, expires_on: null}
}

async function startLotPost(materialReturn: MaterialReturn): Promise<void> {
  const ticket = ++loadTicket
  activeReturnId.value = materialReturn.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableMaterialReturnLots(materialReturn.id)
    if (ticket !== loadTicket || activeReturnId.value !== materialReturn.id) return
    if (result.material_issue_id !== materialReturn.material_issue_id
        || result.warehouse_id !== materialReturn.warehouse_id
        || result.lines.length !== materialReturn.lines.length
        || result.lines.some(line => !materialReturn.lines.some(item =>
          item.id === line.return_line_id
          && item.material_issue_line_id === line.material_issue_line_id
          && item.component_material_id === line.material_id && item.quantity === line.quantity)))
      throw Error('原领料批次与当前生产退料单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = materialReturn.lines.map(line => ({return_line_id: line.id,
      lots: [newPart(line.quantity)]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: MaterialReturnLotLineInput): void {
  if (line.lots.length < 20) line.lots.push(newPart(''))
}

const lotIssue = computed(() => {
  const materialReturn = activeReturn.value, options = lotOptions.value
  if (!materialReturn || !options || lotDrafts.value.length !== materialReturn.lines.length)
    return '原领料批次尚未读取。'
  for (const line of materialReturn.lines) {
    const draft = lotDrafts.value.find(item => item.return_line_id === line.id)
    const available = options.lines.find(item => item.return_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条退料明细至少指定一个回仓实物批次。'
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
        if (!candidate || ids.has(part.lot_id)) return `物料 ${line.sku} 的原领料批次无效或重复。`
        ids.add(part.lot_id)
        if (quantity > (receiptLotMilli(candidate.quantity) ?? 0n))
          return `原领料批次 ${candidate.code} 的剩余可退量不足，请重新读取。`
      }
      total += quantity
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的回仓批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})

async function confirmLotPost(): Promise<void> {
  const materialReturn = activeReturn.value
  if (!materialReturn || lotIssue.value || busy.value || connectionLost.value) return
  await postMaterialReturn(materialReturn.id, lotDrafts.value.map(line => ({
    return_line_id: line.return_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity,
      supplier_lot: part.lot_id === null ? part.supplier_lot?.trim() || null : null,
      manufactured_on: part.lot_id === null ? part.manufactured_on : null,
      expires_on: part.lot_id === null ? part.expires_on : null}))})))
  if (!materialReturns.value.some(item => item.id === materialReturn.id && item.status === 'draft'))
    closeLotPost()
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createMaterialReturn, { busy, error, notice }, createOpen)
}
async function submitReverse(item: MaterialReturn): Promise<void> {
  const reason = reversalReasons.value[item.id]?.trim() ?? ''
  if (!reason || busy.value || connectionLost.value || item.status !== 'posted') return
  await reverseMaterialReturn(item.id, reason)
  if (materialReturns.value.some(record => record.id === item.id && record.status === 'reversed'))
    delete reversalReasons.value[item.id]
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  materialReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const materialReturnFormRows = computed(() => documentRows(materialReturnForm.value.lines))
const materialReturnFormColumns = [
  { key: 'material', title: '原单物料', width: '300' },
  { key: 'remaining', title: '可退数量', width: '130' },
  { key: 'quantity', title: '本次退料数量', width: '160' },
  { key: 'actions', title: '操作', width: '100' },
]
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('material_return.create')"
          v-model:show="createOpen"
          title="新建生产退料单"
          :data="materialReturnFormRows"
          :columns="materialReturnFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!materialReturnForm.lines.length"
          submit-label="保存退料草稿"
          :min-table-width="800"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >原领料单<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="materialReturnForm.material_issue_id"
                required
                @change="selectReturnIssue(materialReturnForm.material_issue_id)"
                :options="[
                  { label: '选择可退领料单', value: 0, disabled: true },
                  ...materialIssues
                    .filter(
                      (entry) =>
                        entry.status === 'posted' &&
                        workOrders.some(
                          (order) => order.id === entry.work_order_id && order.status === 'in_progress'
                        ) &&
                        entry.lines.some((line) => Number(line.returnable_quantity) > 0)
                    )
                    .map((item) => ({
                      label: (
                        ' #' +
                        item.id +
                        ' · 工单 #' +
                        item.work_order_id +
                        ' · ' +
                        item.warehouse_name
                      ).trim(),
                      value: item.id
                    }))
                ]" /></label
            ><label
              >退料原因<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="materialReturnForm.reason"
                required
                maxlength="200"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">
                只退回已确认领料的组件，确认后入原领料仓库，并恢复工单可领数量。请按实际退回数量填写。
              </p>
            </div>
          </template>
          <template #cell-material="{ row: { line } }">{{
            selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)?.material_name
          }}</template>
          <template #cell-remaining="{ row: { line } }">{{
            selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)?.returnable_quantity
          }}</template>
          <template #cell-quantity="{ row: { line } }"
            ><label
              >本次退料数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
                :max="
                  selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)
                    ?.returnable_quantity
                "
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || busy"
              @click="
                materialReturnForm.lines = materialReturnForm.lines.filter(
                  (item) => item.material_issue_line_id !== line.material_issue_line_id
                )
              "
              variant="text"
            >
              本次不退
            </AppButton></template
          >
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产退料"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('material_return.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建生产退料单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产退料
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            #{{ item.id }} · 原领料 #{{ item.material_issue_id }} · 工单 #{{ item.work_order_id }} ·
            {{ item.warehouse_name }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} · {{ item.reason }}
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{ { draft: '草稿', posted: '已确认', cancelled: '已取消', reversed: '已冲销' }[item.status] }}
        </span>
        <small v-if="item.reversal_reason" class="muted">
          {{ item.reversed_at ? localTime(item.reversed_at) : '' }} · 冲销原因：{{ item.reversal_reason }}
        </small>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
            <small v-if="['posted', 'reversed'].includes(item.status) && line.physical_lots.length" class="return-lot-proof">
              实物批次：{{ line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
            </small>
            <small v-else-if="['posted', 'reversed'].includes(item.status)" class="return-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('material_return.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            核对批次并确认退料
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('material_return.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelMaterialReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
          <template v-if="item.status === 'posted' && can('material_return.reverse')">
            <label>冲销原因
              <AppInput v-model.trim="reversalReasons[item.id]" maxlength="200" placeholder="填写错误确认依据" />
            </label>
            <AppButton type="button" variant="secondary" size="small"
              :disabled="busy || connectionLost || !reversalReasons[item.id]?.trim()"
              @click="submitReverse(item)">冲销已确认退料</AppButton>
          </template>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无生产退料记录' }}</strong>
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
      <form v-if="activeReturn && can('material_return.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>生产退料 #{{ activeReturn.id }} · 回仓实物批次</h2>
        <p>可归回原领料已记录的批次，数量不得超过该批次剩余可退量；实物无法对应原批次或原领料未记录批次时，登记“退料新批次”。退回仓库为 {{ activeReturn.warehouse_name }}。</p>
        <p v-if="lotLoading">正在读取原领料批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.return_line_id" class="stack return-lot-line">
          <h3>{{ activeReturn.lines.find(item=>item.id===line.return_line_id)?.sku }} · 退料量 {{ activeReturn.lines.find(item=>item.id===line.return_line_id)?.quantity }}</h3>
          <p v-if="!lotOptions?.lines.find(item=>item.return_line_id===line.return_line_id)?.lots.length" class="muted">原领料未登记可退批次，须登记退料新批次；旧单据仍可在批次核对页追踪差额。</p>
          <div v-for="(part,index) in line.lots" :key="index" class="return-lot-grid">
            <label>回仓批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'登记退料新批次',value:null},
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
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认退料并固定批次</AppButton>
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
