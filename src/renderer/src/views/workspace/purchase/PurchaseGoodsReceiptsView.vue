<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, purchaseOrders, goodsReceipts, warehouses, goodsReceiptForm } = storeToRefs(store)
const { can, localTime, chooseGoodsReceiptOrder, createGoodsReceipt, confirmGoodsReceipt,
  cancelGoodsReceipt } = store
const query = ref('')
const showForm = ref(false)
const selectedOrder = computed(() => purchaseOrders.value.find((item) => item.id === goodsReceiptForm.value.purchase_order_id))
const filtered = computed(() => goodsReceipts.value.filter((item) =>
  [item.id, item.purchase_order_id, item.supplier_name, item.reference, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'document', title: '收货单' }, { key: 'warehouse', title: '仓库与状态' },
  { key: 'lines', title: '收货明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createGoodsReceipt, { busy, error, notice }, showForm)
}
</script>

<template>
  <section class="stack">
    <!-- 列表保留操作与筛选，页面标题在卡片外统一显示。 -->
    <WorkspaceTable dataset="goodsReceipts" :query="query"
      :show-title="false"
      :data="filtered"
      title="采购收货"
      :columns="columns"
      :min-table-width="940"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_receiving.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建收货单</AppButton
        >
      </template>
      <template #filters>
        <label>搜索收货单<AppInput v-model="query" placeholder="单号、供应商或物料" /></label>
      </template>
      <template #beforeTable>
        <NModal
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="showForm && can('purchase_receiving.create')"
            class="stack"
            @submit.prevent="submitCreate"
          >
            <h3>记录本批采购收货</h3>
            <div class="form-grid">
              <label
                >采购订单<WorkspaceSelect remote-dataset="purchaseOrders" :remote-filters="{statuses:'confirmed,partially_received'}"
                  v-model="goodsReceiptForm.purchase_order_id"
                  required
                  @change="chooseGoodsReceiptOrder"
                  :options="[
                    { label: '选择待收货订单', value: 0, disabled: true },
                    ...purchaseOrders
                      .filter((item) => ['confirmed', 'partially_received'].includes(item.status))
                      .map((order) => ({
                        label: ('#' + order.id + ' · ' + order.supplier_name).trim(),
                        value: order.id
                      }))
                  ]"
              /></label>
              <label
                >目标仓库<WorkspaceSelect remote-dataset="warehouses"
                  v-model="goodsReceiptForm.warehouse_id"
                  required
                  :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
              /></label>
              <label
                >送货参考号<AppInput v-model.trim="goodsReceiptForm.reference" maxlength="100"
              /></label>
            </div>
            <p class="muted">仅合格实收数量生成待入库单；拒收数量不增加库存，须填写原因。</p>
            <div
              v-for="(line, index) in goodsReceiptForm.lines"
              :key="line.purchase_order_line_id"
              class="line-row"
            >
              <span>{{
                selectedOrder?.lines.find((item) => item.id === line.purchase_order_line_id)
                  ?.material_name
              }}</span>
              <label
                >合格实收<AppInput
                  v-model.trim="line.accepted_quantity"
                  type="number"
                  min="0"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <label
                >拒收数量<AppInput
                  v-model.trim="line.rejected_quantity"
                  type="number"
                  min="0"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <label
                >拒收原因<AppInput
                  v-model.trim="line.rejection_reason"
                  maxlength="200"
                  :required="Number(line.rejected_quantity) > 0"
              /></label>
              <AppButton
                type="button"
                :disabled="goodsReceiptForm.lines.length === 1"
                @click="goodsReceiptForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                :disabled="busy || connectionLost || !goodsReceiptForm.lines.length"
                variant="primary"
                type="submit"
                >保存收货草稿</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >收起</AppButton
              >
            </div>
          </form>
        </NModal>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>#{{ item.id }} · {{ item.supplier_name }}</strong
        ><small>{{ localTime(item.created_at) }}</small
        ><small
          >采购订单 #{{ item.purchase_order_id
          }}<span v-if="item.reference"> · {{ item.reference }}</span></small
        ></template
      >
      <template #cell-warehouse="{ row: item }"
        >{{ item.warehouse_name
        }}<small>{{
          item.status === 'draft'
            ? '待确认收货'
            : item.status === 'cancelled'
              ? '已取消'
              : item.inbound_receipt_id
                ? '已确认收货'
                : '全数拒收'
        }}</small
        ><small v-if="item.inbound_receipt_id"
          >入库单 #{{ item.inbound_receipt_id }} ·
          {{
            item.inbound_reversal_id
              ? '已冲销'
              : item.inbound_status === 'posted'
                ? '已入库'
                : '待入库'
          }}</small
        ></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }}：合格 {{ line.accepted_quantity }}，拒收
          {{ line.rejected_quantity }} {{ line.unit
          }}<small v-if="line.rejection_reason">{{ line.rejection_reason }}</small>
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('purchase_receiving.confirm')"
            :disabled="busy || connectionLost"
            @click="confirmGoodsReceipt(item.id)"
            variant="primary"
            size="small"
            type="button"
            >确认收货</AppButton
          >
          <AppButton
            v-if="item.status === 'draft' && can('purchase_receiving.cancel')"
            :disabled="busy || connectionLost"
            @click="cancelGoodsReceipt(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消草稿</AppButton
          >
        </div></template
      >
      <template #empty>{{ query ? '没有匹配的采购收货单。' : '暂无采购收货单。' }}</template>
    </WorkspaceTable>
  </section>
</template>
