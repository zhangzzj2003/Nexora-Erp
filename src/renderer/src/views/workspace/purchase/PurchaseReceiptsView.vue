<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { useAppStore } from '../../../store/app-store'

// 入库确认沿用原单据接口；新建采购入库草稿由采购收货确认时自动完成。
const { busy, receipts, receiptReversalReasons, can, localTime, postReceipt, reverseReceipt } =
  useAppStore()
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  receipts.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
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
    <WorkspaceTable dataset="receipts" :query="recordQuery"
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
          <strong>#{{ item.id }} · {{ item.supplier_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.purchase_order_id">· 采购订单 #{{ item.purchase_order_id }}</span>
            <span v-if="item.goods_receipt_id">· 采购收货 #{{ item.goods_receipt_id }}</span>
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
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('receipt.post')"
            type="button"
            :disabled="busy"
            @click="postReceipt(item.id)"
            variant="primary"
            size="small"
          >
            确认入库
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
  </section>
</template>
