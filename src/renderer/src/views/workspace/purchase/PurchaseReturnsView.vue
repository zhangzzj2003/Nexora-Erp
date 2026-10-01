<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
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

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createPurchaseReturn, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  purchaseReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.supplier_name,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('purchase_return.create')"
      v-model:show="createOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">PURCHASE RETURN</p>
          <h2>新建采购退货</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <p class="muted">
        退货从原入库仓库扣减。若货物已调走，请先调回；未关联采购订单的历史入库单不显示退货金额。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >原入库单<WorkspaceSelect remote-dataset="receipts" :remote-filters="{status:'posted'}"
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
                    label: (
                      ' #' +
                      item.id +
                      ' · ' +
                      item.supplier_name +
                      ' · ' +
                      item.warehouse_name
                    ).trim(),
                    value: item.id
                  }))
              ]" /></label
          ><label
            >退货原因<AppInput v-model.trim="purchaseReturnForm.reason" required maxlength="200"
          /></label>
        </div>
        <h3>退货明细</h3>
        <div
          v-for="(line, index) in purchaseReturnForm.lines"
          :key="line.receipt_line_id"
          class="line-row"
        >
          <label
            >原入库物料<AppInput
              :model-value="
                selectedPurchaseReturnReceipt?.lines.find(
                  (item) => item.id === line.receipt_line_id
                )?.material_name
              "
              disabled /></label
          ><label
            >退货数量（最多
            {{
              selectedPurchaseReturnReceipt?.lines.find((item) => item.id === line.receipt_line_id)
                ?.returnable_quantity
            }}）<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              :max="
                selectedPurchaseReturnReceipt?.lines.find(
                  (item) => item.id === line.receipt_line_id
                )?.returnable_quantity
              "
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            @click="purchaseReturnForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="submit"
            :disabled="busy || !purchaseReturnForm.lines.length"
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable dataset="purchaseReturns" :query="recordQuery"
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
          <strong>#{{ item.id }} · {{ item.supplier_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 原入库单 #{{ item.receipt_id }} · {{ item.reason }} ·
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
                  : item.outbound_id
                    ? `待仓库出库 #${item.outbound_id}`
                    : '草稿'
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
          <AppButton
            v-if="item.status === 'draft' && !item.outbound_id && can('purchase_return.submit')"
            type="button"
            :disabled="busy"
            @click="submitPurchaseReturn(item.id)"
            variant="primary"
            size="small"
          >
            提交待出库
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('purchase_return.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelPurchaseReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('purchase_return.reverse')"
          class="inline-form"
          @submit.prevent="reversePurchaseReturn(item.id)"
        >
          <label>
            冲销原因
            <AppInput
              v-model.trim="purchaseReturnReversalReasons[item.id]"
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
  </section>
</template>
