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
  postShipment,
  cancelShipment,
  reverseShipment
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createShipment, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  shipments.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.customer_name,
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
    <NModal
      v-if="can('shipment.create')"
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
          <p class="eyebrow">SALES SHIPMENT</p>
          <h2>新建出库单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >销售订单<WorkspaceSelect remote-dataset="salesOrders" :remote-filters="{statuses:'confirmed,partially_shipped'}"
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
            >出库仓库<WorkspaceSelect remote-dataset="warehouses"
              v-model="shipmentForm.warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >参考单号（可选）<AppInput v-model.trim="shipmentForm.reference" maxlength="100"
          /></label>
        </div>
        <p class="muted">确认出库时将从所选仓库扣减库存，并再次核对销售订单剩余数量。</p>
        <div v-for="(line, index) in shipmentForm.lines" :key="index" class="line-row">
          <label
            >物料<WorkspaceSelect remote-dataset="materials"
              v-model="line.material_id"
              required
              :options="[
                { label: '选择物料'.trim(), value: 0, disabled: true },
                ...materials.map((item) => ({
                  label: (item.sku + ' · ' + item.name).trim(),
                  value: item.id
                }))
              ]" /></label
          ><label
            >出库数量<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="shipmentForm.lines.length === 1"
            @click="shipmentForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="shipmentForm.lines.push({ material_id: 0, quantity: '1' })"
            variant="secondary"
          >
            添加明细</AppButton
          ><AppButton
            type="submit"
            :disabled="
              busy ||
              !materials.length ||
              !salesOrders.some((entry) =>
                ['confirmed', 'partially_shipped'].includes(entry.status)
              )
            "
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable dataset="shipments" :query="recordQuery"
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
          <strong>#{{ item.id }} · {{ item.customer_name }} · {{ item.warehouse_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 销售订单 #{{ item.sales_order_id }} · 创建人
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
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('shipment.post')"
            type="button"
            :disabled="busy"
            @click="postShipment(item.id)"
            variant="primary"
            size="small"
          >
            确认出库
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
  </section>
</template>
