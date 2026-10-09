<script setup lang="ts">
// 退货只在批准后转出库；共用审批弹窗保留固定正文和完整历史。
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
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
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { useAppStore, usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  receipts,
  purchaseReturns,
  purchaseReturnForm,
  purchaseReturnReversalReasons,
  can,
  selectedPurchaseReturnReceipt,
  localTime,
  choosePurchaseReturnReceipt,
  createPurchaseReturn,
  submitPurchaseReturn,
  cancelPurchaseReturn,
  reversePurchaseReturn
} = useAppStore()
const approvalStore = usePiniaAppStore()

// 冲销只能使用另行批准的固定原因，不能改用未审核的列表草稿。
async function reverseApproved(identifier: number): Promise<void> {
  if (!await approvalStore.openDocumentApproval({ document_type: 'PurchaseReturn', document_id: identifier, intent: 'reverse' })) return
  const record = approvalStore.documentApprovalRecord
  if (record?.status !== 'approved' || !record.reversal_reason) return
  purchaseReturnReversalReasons.value[identifier] = record.reversal_reason
  approvalStore.closeDocumentApproval()
  await reversePurchaseReturn(identifier)
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createPurchaseReturn, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  purchaseReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.supplier_name,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const purchaseReturnFormRows = computed(() => documentRows(purchaseReturnForm.value.lines))
const purchaseReturnFormColumns = [
  { key: 'material', title: '原入库物料', width: '300' },
  { key: 'quantity', title: '退货数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          material-supply
          v-if="can('purchase_return.create')"
          v-model:show="createOpen"
          title="新建采购退货"
          :data="purchaseReturnFormRows"
          :columns="purchaseReturnFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!purchaseReturnForm.lines.length"
          submit-label="保存草稿"
          :min-table-width="800"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >原入库单<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="purchaseReturnForm.receipt_id"
                required
                @change="choosePurchaseReturnReceipt"
                :options="[
                  { label: '选择可退货的入库单', value: 0, disabled: true },
                  ...receipts
                    .filter(
                      (entry) =>
                        entry.status === 'posted' &&
                        entry.lines.some((line) => Number(line.returnable_quantity) > 0)
                    )
                    .map((item) => ({
                      label: (' #' + item.id + ' · ' + item.supplier_name + ' · ' + item.warehouse_name).trim(),
                      value: item.id
                    }))
                ]" /></label
            ><label
              >退货原因<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseReturnForm.reason"
                required
                maxlength="200"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">
                退货从原入库仓库扣减。若货物已调走，请先调回；未关联采购订单的历史入库单不显示退货金额。
              </p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >原入库物料<AppInput
                :model-value="
                  selectedPurchaseReturnReceipt?.lines.find((item) => item.id === line.receipt_line_id)
                    ?.material_name
                "
                disabled /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >退货数量（最多
              {{
                selectedPurchaseReturnReceipt?.lines.find((item) => item.id === line.receipt_line_id)
                  ?.returnable_quantity
              }}）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
                :max="
                  selectedPurchaseReturnReceipt?.lines.find((item) => item.id === line.receipt_line_id)
                    ?.returnable_quantity
                "
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              :disabled="busy || connectionLost"
              type="button"
              @click="purchaseReturnForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="采购退货"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_return.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建采购退货
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索采购退货
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ item.supplier_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 原入库单 {{ relatedDocumentLabel(item, 'receipt') }} · {{ item.reason }} ·
            创建人 {{ item.created_by_name }} · 原价金额
            {{ item.total_amount === null ? '待核对' : `¥${item.total_amount}` }}
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
                ? '已退供应商'
                : item.status === 'cancelled'
                  ? '已取消'
                  : item.outbound_id && item.approval?.status === 'executed'
                    ? `待仓库出库 ${relatedDocumentLabel(item, 'outbound')}`
                    : ({ submitted: '审批中', approved: '已批准待转出库', rejected: '已驳回', withdrawn: '已撤回', draft: '待送审', executed: '已转出库' })[item.approval?.status ?? 'draft']
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }} ·
            {{ line.line_total === null ? '金额待核对' : `¥${line.line_total}` }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <!-- 旧待出库草稿的父退货仍须补走审批，不能因已有子单误显示为已转单。 -->
          <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
            @click="approvalStore.openDocumentApproval({ document_type: 'PurchaseReturn', document_id: item.id, intent: 'execute' })">
            {{ item.status === 'draft' && item.approval?.status !== 'executed' ? '单据审批' : '审批记录' }}
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('purchase_return.submit')"
            type="button"
            :disabled="busy || connectionLost"
            @click="submitPurchaseReturn(item.id)"
            variant="primary"
            size="small"
          >
            生成出库草稿
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && !['submitted', 'approved'].includes(item.approval?.status ?? '') && !['submitted', 'approved'].includes(item.outbound_approval?.status ?? '') && can('purchase_return.cancel')"
            type="button"
            :disabled="busy || connectionLost"
            @click="cancelPurchaseReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <div v-if="item.status === 'posted'" class="form-actions">
          <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
            @click="approvalStore.openDocumentApproval({ document_type: 'PurchaseReturn', document_id: item.id, intent: 'reverse' })">
            {{ item.reversal_id ? '冲销审批记录' : '冲销审批' }}
          </AppButton>
          <AppButton v-if="!item.reversal_id && item.reversal_approval?.status === 'approved' && can('purchase_return.reverse')"
            type="button" :disabled="busy || connectionLost" variant="secondary" size="small"
            @click="reverseApproved(item.id)">执行已批准冲销</AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无采购退货记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
    <DocumentApprovalDialog />
  </section>
</template>
