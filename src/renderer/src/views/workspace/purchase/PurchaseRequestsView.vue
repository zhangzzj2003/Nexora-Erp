<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NPopconfirm } from 'naive-ui'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
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
  [documentSearch(item), item.id, item.reference, item.note, item.status, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const selectedRequest = computed(() => purchaseRequests.value.find((item) => item.id === requestConversionForm.value.requestId))
const columns = [
  { key: 'id', title: '申请' }, { key: 'status', title: '状态' },
  { key: 'lines', title: '明细与待转数量' }, { key: 'actions', title: '操作' }
]
const statusName = { draft: '草稿', submitted: '待审批', approved: '已批准', rejected: '已驳回', cancelled: '已取消' }

function openEditor(requestId?: number): void {
  // 收起后再次打开同一份草稿不重新初始化；切换新单或其他申请才载入对应表单。
  if (purchaseRequestForm.value.requestId !== (requestId ?? null)) editPurchaseRequest(requestId)
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
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const purchaseRequestFormRows = computed(() => documentRows(purchaseRequestForm.value.lines))
const purchaseRequestFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '申请数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const requestConversionFormRows = computed(() => documentRows(requestConversionForm.value.lines))
const requestConversionFormColumns = [
  { key: 'material', title: '物料', width: '300' },
  { key: 'quantity', title: '本次数量', width: '150' },
  { key: 'unitPrice', title: '单价（元）', width: '150' },
]
</script>

<template>
  <section class="stack">
    <!-- 列表保留操作与筛选，页面标题在卡片外统一显示。 -->
    <WorkspaceTable
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
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="showForm && can('purchase_request.create')"
          v-model:show="showForm"
          :title="purchaseRequestForm.requestId ? '修改采购申请' : '新建采购申请'"
          :data="purchaseRequestFormRows"
          :columns="purchaseRequestFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="purchaseRequestForm.lines.length >= 100"
          @add-material="purchaseRequestForm.lines.push({ material_id: 0, quantity: '1' })"
          @submit="save"
        >
          <template #basicInfo
            ><label
              >参考单号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseRequestForm.reference"
                maxlength="100"
            /></label>
            <label
              >采购说明<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseRequestForm.note"
                maxlength="500"
            /></label>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >物料<WorkspaceMaterialSelect
                :disabled="busy || connectionLost"
                :materials="materials"
                v-model="line.material_id"
                required
                :options="[
                  { label: '选择物料', value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >申请数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || purchaseRequestForm.lines.length === 1"
              @click="purchaseRequestForm.lines.splice(index, 1)"
              variant="text"
              >移除</AppButton
            ></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="selectedRequest && can('purchase_order.create')"
          v-model:show="conversionOpen"
          :title="`申请 ${selectedRequest ? documentLabel(selectedRequest) : ''} 转采购订单`"
          :data="requestConversionFormRows"
          :columns="requestConversionFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="
            busy || connectionLost || !requestConversionForm.lines.some((line) => Number(line.quantity) > 0)
          "
          submit-label="生成订单草稿"
          :min-table-width="800"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitConversion"
        >
          <template #basicInfo
            ><label
              >供应商<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="requestConversionForm.supplier_id"
                required
                :options="[
                  { label: '选择供应商', value: 0, disabled: true },
                  ...suppliers.map((item) => ({ label: item.name, value: item.id }))
                ]"
            /></label>
            <label
              >参考单号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="requestConversionForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">本批不采购的明细填 0；可再次从剩余数量生成其他订单。</p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><span>{{
              selectedRequest.lines.find((item) => item.id === line.purchase_request_line_id)?.material_name
            }}</span></template
          >
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >本次数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-unitPrice="{ row: { line, index } }"
            ><label
              >单价（元）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.unit_price"
                type="number"
                min="0"
                max="1000000000"
                step="0.0001"
                required /></label
          ></template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-id="{ row: item }"
        ><strong>{{ documentLabel(item) }}</strong
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
