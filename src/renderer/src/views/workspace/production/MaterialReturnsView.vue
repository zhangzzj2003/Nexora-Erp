<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
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
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
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
let loadTicket = 0
const activeReturn = computed(() => materialReturns.value.find(item =>
  item.id === activeReturnId.value && item.status === 'draft' && item.approval?.status === 'approved') ?? null)

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
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  materialReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
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
// 执行时重读服务端批准内容，禁止临时原因替换固定冲销依据。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await store.openDocumentApproval({ document_type: 'MaterialReturn', document_id: identifier, intent: 'reverse' })) return
  const record = store.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  store.closeDocumentApproval()
  await reverseMaterialReturn(identifier, record.reversal_reason)
}
// 审批状态独立于下达、质检和库存执行状态，避免上游批准被误认为本单批准。
const approvalLabels = { draft: '未送审', submitted: '审批中', approved: '已批准，待确认', rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }
</script>

<template>
  <section class="stack">
    <DocumentApprovalDialog />
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
            {{ documentLabel(item) }} · 原领料 {{ relatedDocumentLabel(item, 'material_issue') }} · 工单 {{ relatedDocumentLabel(item, 'work_order') }} ·
            {{ item.warehouse_name }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} · {{ item.reason }}
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{ { draft: approvalLabels[item.approval?.status ?? 'draft'], posted: '已确认', cancelled: '已取消', reversed: '已冲销' }[item.status] }}
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
            <small v-else-if="['posted', 'reversed'].includes(item.status)" class="return-lot-proof">普通确认未指定实物批次，数量在批次核对页显示为差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton type="button" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'MaterialReturn', document_id: item.id, intent: 'execute' })">单据审批</AppButton>
          <!-- 冲销另行送审；完成后保留查询入口而不允许再次执行。 -->
          <AppButton v-if="item.status === 'reversed'" type="button" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'MaterialReturn', document_id: item.id, intent: 'reverse' })">冲销审批记录</AppButton>
          <template v-if="item.status === 'posted' && can('material_return.reverse')">
            <AppButton type="button" size="small" :disabled="busy || connectionLost"
              @click="store.openDocumentApproval({ document_type: 'MaterialReturn', document_id: item.id, intent: 'reverse' })">冲销审批</AppButton>
            <AppButton v-if="item.reversal_approval?.status === 'approved'" type="button" size="small" :disabled="busy || connectionLost"
              @click="reverseApproved(item.id)">执行已批准冲销</AppButton>
          </template>
          <template v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('material_return.post')">
            <AppButton type="button" variant="primary" size="small" :disabled="busy || connectionLost" @click="postMaterialReturn(item.id)">确认退料</AppButton>
            <AppButton type="button" size="small" :disabled="busy || connectionLost" @click="startLotPost(item)">指定实物批次（可选）</AppButton>
          </template>
          <AppButton
            v-if="item.status === 'draft' && !['submitted', 'approved'].includes(item.approval?.status ?? '') && can('material_return.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelMaterialReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>

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
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog v-if="activeReturn && can('material_return.post')" :show="true"
      title="生产退料 · 回仓批次" :document-number="documentLabel(activeReturn)"
      :hint="'可归回原领料已记录的批次，数量不得超过该批次剩余可退量；实物无法对应原批次或原领料未记录批次时，登记“退料新批次”。退回仓库为 ' + activeReturn.warehouse_name + '。'"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="确认退料"
      :loading="lotLoading" :load-error="lotLoadError" loading-text="正在读取原领料批次…"
      @update:show="value => { if (!value) closeLotPost() }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.return_line_id" :lots="line.lots"
        :sku="activeReturn.lines.find(item => item.id === line.return_line_id)?.sku" :material-name="activeReturn.lines.find(item => item.id === line.return_line_id)?.material_name"
        :unit="activeReturn.lines.find(item => item.id === line.return_line_id)?.unit" :expected="activeReturn.lines.find(item => item.id === line.return_line_id)?.quantity ?? ''"
        expected-label="应退料" quantity-label="批次数量" :selectable="true" :new-lot-value="null"
        :options="[{label:'登记退料新批次',value:null},
                ...(lotOptions?.lines.find(item=>item.return_line_id===line.return_line_id)?.lots ?? [])
                  .map(lot=>({label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 剩余可退 ${lot.quantity}`,
                    value:lot.lot_id}))]"
        :disabled="busy || connectionLost || lotLoading" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)">
        <span v-if="!lotOptions?.lines.find(item=>item.return_line_id===line.return_line_id)?.lots.length">原领料未登记可退批次，须登记退料新批次；旧单据仍可在批次核对页追踪差额。</span>
      </WorkspaceLotLineEditor>
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped>
.return-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
</style>
