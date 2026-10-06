<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import {datePickerString,vDateField} from '../../../utils/date-field'
import {NDatePicker} from 'naive-ui'
import type {Receipt} from '../../../../../shared/erp-api'
import type {ReceiptLotLineInput} from '../../../../../shared/receipt-lot-api'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import { computed, ref } from 'vue'
import { useAppStore } from '../../../store/app-store'

// 入库确认沿用原单据接口；新建采购入库草稿由采购收货确认时自动完成。
const { busy, receipts, receiptReversalReasons, can, localTime, postReceipt, reverseReceipt } =
  useAppStore()
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const activeReceiptId = ref(0)
const lotDrafts = ref<ReceiptLotLineInput[]>([])
const activeReceipt = computed(() => receipts.value.find(item =>
  item.id === activeReceiptId.value && item.status === 'draft') ?? null)
function startLotPost(receipt: Receipt): void {
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
  if (!activeReceipt.value || lotIssue.value || busy.value) return
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
          {{ item.reversal_id ? '已冲销' : item.status === 'posted' ? '已入库' : '待确认' }}
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
            <small v-else-if="item.status === 'posted'" class="receipt-lot-proof">未登记实物批次，数量在批次核对页显示为差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('receipt.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            登记批次并确认
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('receipt.reverse')"
          class="inline-form"
          @submit.prevent="reverseReceipt(item.id)"
        >
          <label>
            冲销原因
            <AppInput
              v-model.trim="receiptReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原入库为何需要冲销"
            />
          </label>
          <AppButton type="submit" :disabled="busy" variant="secondary" size="small"
            >冲销已确认入库</AppButton
          >
        </form>
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
    <form v-if="activeReceipt && can('receipt.post')" class="stack receipt-lot-editor" @submit.prevent="confirmLotPost">
      <div class="receipt-lot-heading"><h2>入库单 {{ documentLabel(activeReceipt) }} · 实物批次</h2>
        <AppButton type="button" :disabled="busy" @click="activeReceiptId=0">返回列表</AppButton></div>
      <p>按实际收货情况逐行登记批次，批次数量之和须等于入库数量。供应商批号和日期缺失时留空，系统会保留独立的入库来源编号。</p>
      <section v-for="line in lotDrafts" :key="line.receipt_line_id" class="stack receipt-lot-line">
        <h3>{{ activeReceipt.lines.find(item=>item.id===line.receipt_line_id)?.sku }} · {{ activeReceipt.lines.find(item=>item.id===line.receipt_line_id)?.material_name }} · {{ activeReceipt.lines.find(item=>item.id===line.receipt_line_id)?.quantity }} {{ activeReceipt.lines.find(item=>item.id===line.receipt_line_id)?.unit }}</h3>
        <div v-for="(part,index) in line.lots" :key="index" class="receipt-lot-grid">
          <label>批次数量<AppInput v-model="part.quantity" inputmode="decimal" required :disabled="busy" /></label>
          <label>供应商批号<AppInput v-model.trim="part.supplier_lot" maxlength="100" placeholder="未提供则留空" :disabled="busy" /></label>
          <label>生产日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.manufactured_on" :disabled="busy" @update:formatted-value="value=>part.manufactured_on=datePickerString(value)||null" /></label>
          <label>失效日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.expires_on" :disabled="busy" @update:formatted-value="value=>part.expires_on=datePickerString(value)||null" /></label>
          <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
        </div>
        <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
      </section>
      <p v-if="lotIssue" role="alert">{{ lotIssue }}</p>
      <AppButton type="submit" variant="primary" :disabled="busy || !!lotIssue">确认入库并固定批次</AppButton>
    </form>
  </section>
</template>

<style scoped>
.receipt-lot-editor{padding:18px;border:1px solid var(--workspace-field-border);border-radius:12px}
.receipt-lot-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.receipt-lot-heading h2{margin:0}
.receipt-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.receipt-lot-line h3{margin:0}.receipt-lot-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;align-items:end}
.receipt-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:950px){.receipt-lot-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}}
@media(max-width:550px){.receipt-lot-grid{grid-template-columns:1fr}}
</style>
