<script setup lang="ts">
// 批准与业务执行分开，审批入口复用共享 Pinia 和固定内容弹窗。
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
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
  [documentSearch(item), item.id, item.purchase_order_id, item.supplier_name, item.reference, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'document', title: '收货单' }, { key: 'warehouse', title: '仓库与状态' },
  { key: 'lines', title: '收货明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createGoodsReceipt, { busy, error, notice }, showForm)
}
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const goodsReceiptFormRows = computed(() => documentRows(goodsReceiptForm.value.lines))
const goodsReceiptFormColumns = [
  { key: 'material', title: '原订单物料', width: '300' },
  { key: 'acceptedQuantity', title: '合格实收', width: '150' },
  { key: 'rejectedQuantity', title: '拒收数量', width: '150' },
  { key: 'rejectionReason', title: '拒收原因', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
</script>

<template>
  <section class="stack">
    <!-- 列表保留操作与筛选，页面标题在卡片外统一显示。 -->
    <WorkspaceTable
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
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          material-supply
          :material-id="row => selectedOrder?.lines.find(line => line.id === row.line.purchase_order_line_id)?.material_id ?? 0"
          v-if="showForm && can('purchase_receiving.create')"
          v-model:show="showForm"
          title="记录本批采购收货"
          :data="goodsReceiptFormRows"
          :columns="goodsReceiptFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost || !goodsReceiptForm.lines.length"
          submit-label="保存收货草稿"
          :min-table-width="800"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >采购订单<WorkspaceSelect
                :disabled="busy || connectionLost"
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
              >目标仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="goodsReceiptForm.warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
            /></label>
            <label
              >送货参考号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="goodsReceiptForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">仅合格实收数量生成待入库单；拒收数量不增加库存，须填写原因。</p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><span>{{
              selectedOrder?.lines.find((item) => item.id === line.purchase_order_line_id)?.material_name
            }}</span></template
          >
          <template #cell-acceptedQuantity="{ row: { line, index } }"
            ><label
              >合格实收<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.accepted_quantity"
                type="number"
                min="0"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-rejectedQuantity="{ row: { line, index } }"
            ><label
              >拒收数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.rejected_quantity"
                type="number"
                min="0"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-rejectionReason="{ row: { line, index } }"
            ><label
              >拒收原因<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.rejection_reason"
                maxlength="200"
                :required="Number(line.rejected_quantity) > 0" /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || goodsReceiptForm.lines.length === 1"
              @click="goodsReceiptForm.lines.splice(index, 1)"
              variant="text"
              >移除</AppButton
            ></template
          >
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>{{ documentLabel(item) }} · {{ item.supplier_name }}</strong
        ><small>{{ localTime(item.created_at) }}</small
        ><small
          >采购订单 {{ relatedDocumentLabel(item, 'purchase_order') }}<span v-if="item.reference"> · {{ item.reference }}</span></small
        ></template
      >
      <template #cell-warehouse="{ row: item }"
        >{{ item.warehouse_name
        }}<small>{{
          item.status === 'draft'
            ? ({ submitted: '审批中', approved: '已批准待收货', rejected: '已驳回', withdrawn: '已撤回', draft: '待送审', executed: '已执行' })[item.approval?.status ?? 'draft']
            : item.status === 'cancelled'
              ? '已取消'
              : item.inbound_receipt_id
                ? '已确认收货'
                : '全数拒收'
        }}</small
        ><small v-if="item.inbound_receipt_id"
          >入库单 {{ relatedDocumentLabel(item, 'inbound_receipt') }} ·
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
          <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'PurchaseGoodsReceipt', document_id: item.id, intent: 'execute' })">
            {{ item.status === 'draft' ? '单据审批' : '审批记录' }}
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('purchase_receiving.confirm')"
            :disabled="busy || connectionLost"
            @click="confirmGoodsReceipt(item.id)"
            variant="primary"
            size="small"
            type="button"
            >确认收货</AppButton
          >
          <AppButton
            v-if="item.status === 'draft' && !['submitted', 'approved'].includes(item.approval?.status ?? '') && can('purchase_receiving.cancel')"
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
    <DocumentApprovalDialog />
  </section>
</template>
