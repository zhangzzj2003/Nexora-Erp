<script setup lang="ts">
// 批准与业务执行分开，审批入口复用共享 Pinia 和固定内容弹窗。
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from '../../../components/workspace/WorkspaceLotDialog.vue'
import WorkspaceLotLineEditor from '../../../components/workspace/WorkspaceLotLineEditor.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import type {Receipt} from '../../../../../shared/erp-api'
import type {ReceiptLotLineInput} from '../../../../../shared/receipt-lot-api'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'

// 入库确认沿用原单据接口；新建采购入库草稿由采购收货确认时自动完成。
const store = usePiniaAppStore()
const { busy, connectionLost, receipts, receiptReversalReasons } = storeToRefs(store)
const { can, localTime, postReceipt, reverseReceipt } = store
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const activeReceiptId = ref(0)
const lotDrafts = ref<ReceiptLotLineInput[]>([])
const activeReceipt = computed(() => receipts.value.find(item =>
  item.id === activeReceiptId.value && item.status === 'draft' && item.approval?.status === 'approved') ?? null)
function startLotPost(receipt: Receipt): void {
  // 普通确认不要求批号；仅在已批准后按现场实际情况选择登记实物证据。
  if (receipt.approval?.status !== 'approved' || busy.value || connectionLost.value) return
  activeReceiptId.value = receipt.id
  lotDrafts.value = receipt.lines.map(line => ({receipt_line_id: line.id,
    lots: [{quantity: line.quantity, supplier_lot: null, manufactured_on: null, expires_on: null}]}))
}
function addLot(line: ReceiptLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({quantity: '', supplier_lot: null,
    manufactured_on: null, expires_on: null})
}
const lotIssue = computed(() => {
  const receipt = activeReceipt.value
  if (!receipt || lotDrafts.value.length !== receipt.lines.length) return '入库单明细已经变化，请重新读取。'
  for (const line of receipt.lines) {
    const draft = lotDrafts.value.find(item => item.receipt_line_id === line.id)
    if (!draft || !draft.lots.length || draft.lots.length > 20) return '每条入库明细至少登记一个实物批次。'
    const expected = receiptLotMilli(line.quantity)
    let total = 0n
    for (const part of draft.lots) {
      const value = receiptLotMilli(part.quantity)
      if (value === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      total += value
      if (part.supplier_lot && part.supplier_lot.length > 100) return '供应商批号不能超过 100 字。'
      if (part.manufactured_on && !receiptLotDate(part.manufactured_on)) return '生产日期无效。'
      if (part.expires_on && !receiptLotDate(part.expires_on)) return '失效日期无效。'
      if (part.manufactured_on && part.expires_on && part.expires_on < part.manufactured_on)
        return '失效日期不能早于生产日期。'
    }
    if (expected === null || total !== expected) return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})
async function confirmLotPost(): Promise<void> {
  // 与其他单据一致，断线时保留批次草稿，连接恢复后再确认。
  if (!activeReceipt.value || lotIssue.value || busy.value || connectionLost.value) return
  await postReceipt(activeReceipt.value.id, lotDrafts.value.map(line => ({
    receipt_line_id: line.receipt_line_id,
    lots: line.lots.map(part => ({quantity: part.quantity, supplier_lot: part.supplier_lot?.trim() || null,
      manufactured_on: part.manufactured_on, expires_on: part.expires_on}))})))
}
const filteredRecords = computed(() =>
  receipts.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.supplier_name,
      item.warehouse_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 只执行服务端固定且已批准的冲销原因，不能临时换成列表中的未审输入。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await store.openDocumentApproval({ document_type: 'Receipt', document_id: identifier, intent: 'reverse' })) return
  const record = store.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  receiptReversalReasons.value[identifier] = record.reversal_reason
  store.closeDocumentApproval()
  await reverseReceipt(identifier)
}
</script>

<template>
  <section class="stack">
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="采购入库"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #filters>
        <label>
          搜索采购入库
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>
      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ item.supplier_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.purchase_order_id">· 采购订单 {{ relatedDocumentLabel(item, 'purchase_order') }}</span>
            <span v-if="item.goods_receipt_id">· 采购收货 {{ relatedDocumentLabel(item, 'goods_receipt') }}</span>
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
          {{ item.reversal_id ? '已冲销' : item.status === 'posted' ? '已入库' : ({ submitted: '审批中', approved: '已批准待入库', rejected: '已驳回', withdrawn: '已撤回', draft: '待送审', executed: '已执行' })[item.approval?.status ?? 'draft'] }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }} · 已退
            {{ line.returned_quantity }}
            <small v-if="item.status === 'posted' && line.physical_lots?.length" class="receipt-lot-proof">
              实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；供应商批号 ${lot.supplier_lot || '未提供'}）`).join('、') }}
            </small>
            <small v-else-if="item.status === 'posted'" class="receipt-lot-proof">普通入库，未登记实物批次。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'Receipt', document_id: item.id, intent: 'execute' })">
            {{ item.status === 'draft' ? '单据审批' : '审批记录' }}
          </AppButton>
          <AppButton v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('receipt.post')"
            type="button" :disabled="busy || connectionLost" variant="primary" size="small"
            @click="postReceipt(item.id)">确认入库</AppButton>
          <AppButton
            v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('receipt.post')"
            type="button"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="secondary"
            size="small"
          >
            登记实物批次（可选）
          </AppButton>
        </div>
        <div v-if="item.status === 'posted'" class="form-actions">
          <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'Receipt', document_id: item.id, intent: 'reverse' })">
            {{ item.reversal_id ? '冲销审批记录' : '冲销审批' }}
          </AppButton>
          <AppButton v-if="!item.reversal_id && item.reversal_approval?.status === 'approved' && can('receipt.reverse')"
            type="button" :disabled="busy || connectionLost" variant="secondary" size="small"
            @click="reverseApproved(item.id)">执行已批准冲销</AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无采购入库记录' }}</strong>
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
    <WorkspaceLotDialog v-if="activeReceipt && can('receipt.post')" :show="true"
      title="采购入库 · 批次登记" :document-number="documentLabel(activeReceipt)"
      hint="按实际收货情况逐行登记批次，批次数量之和须等于入库数量。供应商批号和日期缺失时留空，系统会保留独立的入库来源编号。"
      :busy="busy" :disabled="connectionLost" :issue="lotIssue" submit-label="确认入库"
      @update:show="value => { if (!value) activeReceiptId = 0 }" @submit="confirmLotPost">
      <WorkspaceLotLineEditor v-for="line in lotDrafts" :key="line.receipt_line_id" :lots="line.lots"
        :sku="activeReceipt.lines.find(item => item.id === line.receipt_line_id)?.sku" :material-name="activeReceipt.lines.find(item => item.id === line.receipt_line_id)?.material_name"
        :unit="activeReceipt.lines.find(item => item.id === line.receipt_line_id)?.unit" :expected="activeReceipt.lines.find(item => item.id === line.receipt_line_id)?.quantity ?? ''"
        expected-label="应入库" source-label="供应商批号" quantity-label="批次数量"
        :disabled="busy || connectionLost" @add="addLot(line)" @remove="index => line.lots.splice(index, 1)" />
    </WorkspaceLotDialog>
    <DocumentApprovalDialog />
  </section>
</template>

<style scoped>
.receipt-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
</style>
