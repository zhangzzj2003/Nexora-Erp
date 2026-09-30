<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

const store = usePiniaAppStore()
const { busy, error, notice, connectionLost, materials, suppliers, purchaseRequests, purchaseRequestForm,
  requestConversionForm, requestRejectReasons } = storeToRefs(store)
const { can, localTime, editPurchaseRequest, savePurchaseRequest, submitPurchaseRequest,
  approvePurchaseRequest, rejectPurchaseRequest, cancelPurchaseRequest,
  selectRequestConversion, convertPurchaseRequest } = store
const query = ref('')
const showForm = ref(false)
const conversionOpen = ref(false)
const filtered = computed(() => purchaseRequests.value.filter((item) =>
  [item.id, item.reference, item.note, item.status, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const selectedRequest = computed(() => purchaseRequests.value.find((item) => item.id === requestConversionForm.value.requestId))
const columns = [
  { key: 'id', title: '申请' }, { key: 'status', title: '状态' },
  { key: 'lines', title: '明细与待转数量' }, { key: 'actions', title: '操作' }
]
const statusName = { draft: '草稿', submitted: '待审批', approved: '已批准', rejected: '已驳回', cancelled: '已取消' }

function openEditor(requestId?: number): void {
  editPurchaseRequest(requestId)
  showForm.value = true
}

function openConversion(requestId: number): void {
  selectRequestConversion(requestId)
  conversionOpen.value = true
}

async function submitConversion(): Promise<void> {
  await submitCreateDialog(convertPurchaseRequest, { busy, error, notice }, conversionOpen)
}

async function save(): Promise<void> {
  await savePurchaseRequest()
  // 写入失败时保留输入；只有服务端刷新后的申请已存在才关闭表单。
  if (!store.error && !store.connectionLost) showForm.value = false
}
</script>

<template>
  <section class="stack">
    <!-- 列表保留操作与筛选，页面标题在卡片外统一显示。 -->
    <WorkspaceTable dataset="purchaseRequests" :query="query"
      :show-title="false"
      :data="filtered"
      title="采购申请"
      :columns="columns"
      :min-table-width="940"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_request.create')"
          :disabled="busy || connectionLost || !materials.length"
          @click="openEditor()"
          variant="primary"
          type="button"
          >新建采购申请</AppButton
        >
      </template>
      <template #filters>
        <label>搜索申请<AppInput v-model="query" placeholder="单号、物料或状态" /></label>
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
            v-if="showForm && can('purchase_request.create')"
            class="stack"
            @submit.prevent="save"
          >
            <h3>{{ purchaseRequestForm.requestId ? '修改采购申请' : '新建采购申请' }}</h3>
            <div class="form-grid">
              <label
                >参考单号<AppInput v-model.trim="purchaseRequestForm.reference" maxlength="100"
              /></label>
              <label
                >采购说明<AppInput v-model.trim="purchaseRequestForm.note" maxlength="500"
              /></label>
            </div>
            <div v-for="(line, index) in purchaseRequestForm.lines" :key="index" class="line-row">
              <label
                >物料<WorkspaceSelect remote-dataset="materials"
                  v-model="line.material_id"
                  required
                  :options="[
                    { label: '选择物料', value: 0, disabled: true },
                    ...materials.map((item) => ({
                      label: (item.sku + ' · ' + item.name).trim(),
                      value: item.id
                    }))
                  ]"
              /></label>
              <label
                >申请数量<AppInput
                  v-model.trim="line.quantity"
                  type="number"
                  min="0.001"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <AppButton
                type="button"
                :disabled="purchaseRequestForm.lines.length === 1"
                @click="purchaseRequestForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                type="button"
                @click="purchaseRequestForm.lines.push({ material_id: 0, quantity: '1' })"
                variant="secondary"
                >添加明细</AppButton
              >
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存草稿</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >收起</AppButton
              >
            </div>
          </form>
        </NModal>
        <NModal
          v-model:show="conversionOpen"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="selectedRequest && can('purchase_order.create')"
            class="stack"
            @submit.prevent="submitConversion"
          >
            <h3>申请 #{{ selectedRequest.id }} 转采购订单</h3>
            <div class="form-grid">
              <label
                >供应商<WorkspaceSelect remote-dataset="suppliers"
                  v-model="requestConversionForm.supplier_id"
                  required
                  :options="[
                    { label: '选择供应商', value: 0, disabled: true },
                    ...suppliers.map((item) => ({ label: item.name, value: item.id }))
                  ]"
              /></label>
              <label
                >参考单号<AppInput v-model.trim="requestConversionForm.reference" maxlength="100"
              /></label>
            </div>
            <p class="muted">本批不采购的明细填 0；可再次从剩余数量生成其他订单。</p>
            <div
              v-for="line in requestConversionForm.lines"
              :key="line.purchase_request_line_id"
              class="line-row"
            >
              <span>{{
                selectedRequest.lines.find((item) => item.id === line.purchase_request_line_id)
                  ?.material_name
              }}</span>
              <label
                >本次数量<AppInput
                  v-model.trim="line.quantity"
                  type="number"
                  min="0"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <label
                >单价（元）<AppInput
                  v-model.trim="line.unit_price"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="0.0001"
                  required
              /></label>
            </div>
            <div class="form-actions">
              <AppButton
                :disabled="
                  busy ||
                  connectionLost ||
                  !requestConversionForm.lines.some((line) => Number(line.quantity) > 0)
                "
                variant="primary"
                type="submit"
                >生成订单草稿</AppButton
              >
              <AppButton
                type="button"
                @click="() => {
                  conversionOpen = false
                  selectRequestConversion(0)
                }"
                variant="secondary"
                >取消</AppButton
              >
            </div>
          </form>
        </NModal>
      </template>
      <template #cell-id="{ row: item }"
        ><strong>#{{ item.id }}</strong
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small></template
      >
      <template #cell-status="{ row: item }"
        ><span class="pill" :class="item.status">{{ statusName[item.status] }}</span
        ><small v-if="item.review_reason">{{ item.review_reason }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }}：申请 {{ line.quantity }} {{ line.unit }}，待转
          {{ line.remaining_quantity }}
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="['draft', 'rejected'].includes(item.status) && can('purchase_request.create')"
            :disabled="busy || connectionLost"
            @click="openEditor(item.id)"
            variant="text"
            type="button"
            >修改</AppButton
          >
          <AppButton
            v-if="item.status === 'draft' && can('purchase_request.submit')"
            :disabled="busy || connectionLost"
            @click="submitPurchaseRequest(item.id)"
            variant="text"
            type="button"
            >提交审批</AppButton
          >
          <AppButton
            v-if="item.status === 'submitted' && can('purchase_request.review')"
            :disabled="busy || connectionLost"
            @click="approvePurchaseRequest(item.id)"
            variant="text"
            type="button"
            >批准</AppButton
          >
          <AppButton
            v-if="
              item.status === 'approved' &&
              can('purchase_order.create') &&
              item.lines.some((line) => Number(line.remaining_quantity) > 0)
            "
            :disabled="busy || connectionLost"
            @click="openConversion(item.id)"
            variant="text"
            type="button"
            >转订单</AppButton
          >
          <NPopconfirm
            v-if="item.status !== 'cancelled' && can('purchase_request.cancel')"
            positive-text="确认"
            negative-text="返回"
            @positive-click="cancelPurchaseRequest(item.id)"
          >
            <template #trigger
              ><AppButton :disabled="busy || connectionLost" variant="text" type="button"
                >取消申请</AppButton
              ></template
            >
            已关联有效订单的申请无法取消。确认取消这张申请？
          </NPopconfirm>
        </div>
        <form
          v-if="item.status === 'submitted' && can('purchase_request.review')"
          class="inline-form"
          @submit.prevent="rejectPurchaseRequest(item.id)"
        >
          <label
            >驳回原因<AppInput
              v-model.trim="requestRejectReasons[item.id]"
              required
              maxlength="200"
          /></label>
          <AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >驳回</AppButton
          >
        </form></template
      >
      <template #empty>{{ query ? '没有匹配的采购申请。' : '暂无采购申请。' }}</template>
    </WorkspaceTable>
  </section>
</template>
