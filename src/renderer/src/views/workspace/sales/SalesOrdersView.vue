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
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import SalesContractAttachments from './SalesContractAttachments.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import type { SalesOrder, SalesOrderContract } from '../../../../../shared/erp-api'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, user, materials, customers, salesOrders, salesForm } = storeToRefs(store)
const { can, localTime, navigateToRoute, createSalesOrder, loadSalesOrderContract, reviseSalesOrderContract, confirmSalesOrder, cancelSalesOrder } = store

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
const contractOpen = ref(false)
const contractLoading = ref(false)
const contractOrder = ref<SalesOrder | null>(null)
const contract = ref<SalesOrderContract | null>(null)
const contractBody = ref('')
const acceptanceReference = ref('')
const contractReason = ref('')
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}:${connectionLost.value}`, () => {
  contractOpen.value = false
  contractOrder.value = null
  contract.value = null
  contractBody.value = ''
  acceptanceReference.value = ''
  contractReason.value = ''
}, { flush: 'sync' })
async function openContract(order: SalesOrder): Promise<void> {
  error.value = ''
  contractOrder.value = order
  contract.value = null
  contractBody.value = ''
  acceptanceReference.value = ''
  contractReason.value = ''
  contractOpen.value = true
  contractLoading.value = true
  const result = await loadSalesOrderContract(order.id)
  if (contractOpen.value && contractOrder.value?.id === order.id) {
    contract.value = result
    contractBody.value = result?.current?.body ?? ''
    contractLoading.value = false
  }
}
async function submitContract(): Promise<void> {
  const order = contractOrder.value
  const current = contract.value
  if (!order || !current) return
  const saved = await reviseSalesOrderContract(order.id, current.version,
    contractBody.value, acceptanceReference.value, contractReason.value)
  if (saved && contractOpen.value && contractOrder.value?.id === order.id) {
    contract.value = saved
    acceptanceReference.value = ''
    contractReason.value = ''
  }
}
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createSalesOrder, { busy, error, notice }, createOpen)
}
// 导航前关闭弹窗，订单草稿继续保存在共享状态中，返回后可继续填写。
function openCustomers(): void {
  createOpen.value = false
  navigateToRoute('customers')
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  salesOrders.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.customer_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const salesFormRows = computed(() => documentRows(salesForm.value.lines))
const salesFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '数量', width: '150' },
  { key: 'unitPrice', title: '单价（元）', width: '150' },
  { key: 'warrantyDays', title: '约定保修天数', width: '150' },
  { key: 'warrantyBasis', title: '合同或承诺依据', width: '220' },
  { key: 'actions', title: '操作', width: '90' },
]
// 审批进度与执行状态分开显示，上游批准不会代替本单批准。
const approvalLabels = { draft: '未送审', submitted: '审批中', approved: '已批准，待确认',
  rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }
</script>

<template>
  <section class="stack">
    <DocumentApprovalDialog />
    <NModal v-model:show="contractOpen" preset="card" title="销售合同正文与修订历史"
      :mask-closable="!busy" :closable="!busy"
      :style="{ width: 'min(900px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }">
      <template v-if="contractOrder">
        <p>销售订单 {{ documentLabel(contractOrder) }} · {{ contractOrder.customer_name }}。正文登记是合同证据；不会自动修改订单金额、明细保修条款或既有售后单。</p>
        <p v-if="contractLoading">正在读取合同历史…</p>
        <template v-else-if="contract">
          <p v-if="contract.version === 0">尚未登记合同正文。旧订单不追认未知条款。</p>
          <form v-if="can('sales_order.confirm') && contractOrder.status !== 'cancelled'" class="contract-form" @submit.prevent="submitContract">
            <label>合同全文<AppInput v-model="contractBody" type="textarea" rows="12"
              maxlength="20000" required :disabled="busy" /></label>
            <label>客户确认依据<AppInput v-model.trim="acceptanceReference" maxlength="400" required :disabled="busy" placeholder="签署件、邮件或确认记录编号" /></label>
            <label>登记或修订原因<AppInput v-model.trim="contractReason" maxlength="200" required :disabled="busy" /></label>
            <AppButton type="submit" variant="primary" :disabled="busy || !contractBody.trim() || !acceptanceReference.trim() || !contractReason.trim()">追加第 {{ contract.version + 1 }} 版</AppButton>
          </form>
          <p v-if="error" role="alert">{{ error }}；输入已保留，请重新打开合同核对最新版本。</p>
          <h3>历史版本</h3>
          <div v-for="revision in contract.history" :key="revision.id" class="contract-revision">
            <p><strong>第 {{ revision.version }} 版</strong> · {{ localTime(revision.created_at) }} · {{ revision.created_by_name }}</p>
            <p>客户确认依据：{{ revision.acceptance_reference }} · 原因：{{ revision.reason }}</p>
            <pre>{{ revision.body }}</pre>
            <SalesContractAttachments :order-id="contract.sales_order_id" :revision-id="revision.id"
              :version="revision.version" />
          </div>
        </template>
      </template>
    </NModal>
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('sales_order.create')"
          v-model:show="createOpen"
          title="新建销售订单"
          :data="salesFormRows"
          :columns="salesFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!customers.length || !materials.length"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="salesForm.lines.length >= 100"
          @add-material="
            salesForm.lines.push({
              material_id: 0,
              quantity: '1',
              unit_price: '0',
              warranty_days: null,
              warranty_basis: ''
            })
          "
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >客户<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="salesForm.customer_id"
                required
                :options="[
                  { label: '选择客户'.trim(), value: 0, disabled: true },
                  ...customers.map((item) => ({ label: item.name.trim(), value: item.id }))
                ]" /></label
            ><label
              >参考单号（可选）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="salesForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <div class="form-actions">
                <span v-if="!customers.length" class="muted">暂无客户，请先建立客户资料。</span>
                <AppButton
                  type="button"
                  :disabled="busy || connectionLost || busy"
                  @click="openCustomers"
                  variant="text"
                >
                  前往客户资料
                </AppButton>
                <span class="muted">订单草稿会保留，返回后可继续填写。</span>
              </div>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >物料<WorkspaceMaterialSelect
                :disabled="busy || connectionLost"
                :materials="materials"
                v-model="line.material_id"
                required
                :options="[
                  { label: '选择物料'.trim(), value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.quantity"
                type="number"
                min="0.001"
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
          <template #cell-warrantyDays="{ row: { line, index } }"
            ><label
              >约定保修天数（可留空）<AppInput
                :disabled="busy || connectionLost"
                :model-value="line.warranty_days === null ? '' : String(line.warranty_days)"
                type="number"
                min="1"
                max="36500"
                step="1"
                @update:model-value="line.warranty_days = $event === '' ? null : Number($event)" /></label
          ></template>
          <template #cell-warrantyBasis="{ row: { line, index } }"
            ><label
              >合同或承诺依据<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.warranty_basis"
                maxlength="400"
                :required="line.warranty_days !== null" /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || salesForm.lines.length === 1"
              @click="salesForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="销售订单"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('sales_order.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建销售订单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索销售订单
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ item.customer_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
            · 总额 ¥{{ item.total_amount }}
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: approvalLabels[item.approval?.status ?? 'draft'],
              confirmed: '待出库',
              partially_shipped: '部分出库',
              shipped: '全部出库',
              cancelled: '已取消'
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} · 已出库 {{ line.shipped_quantity }}/{{ line.quantity }} · 已退
            {{ line.returned_quantity }} · 净交付 {{ line.net_delivered_quantity }}
            {{ line.unit }} · ¥{{ line.unit_price }}/{{ line.unit }}
            <template v-if="line.warranty_days !== null"> · 保修 {{ line.warranty_days }} 天（{{ line.warranty_basis }}）</template>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton type="button" :disabled="busy" @click="openContract(item)" size="small">合同正文</AppButton>
          <AppButton type="button" size="small" :disabled="busy || connectionLost"
            @click="store.openDocumentApproval({ document_type: 'SalesOrder', document_id: item.id, intent: 'execute' })">单据审批</AppButton>
          <template v-if="item.status === 'draft' && item.approval?.status === 'approved' && can('sales_order.confirm')">
            <AppButton type="button" variant="primary" size="small" :disabled="busy || connectionLost" @click="confirmSalesOrder(item.id)">确认订单</AppButton>
          </template>
          <AppButton v-if="['draft', 'confirmed'].includes(item.status) && !['submitted', 'approved'].includes(item.approval?.status ?? '') && can('sales_order.cancel')"
            type="button" size="small" :disabled="busy || connectionLost" @click="cancelSalesOrder(item.id)">取消订单</AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无销售订单记录' }}</strong>
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

<style scoped>
.contract-form { display: grid; gap: 12px; margin: 16px 0; }
.contract-revision { border-top: 1px solid var(--border-color, #d8dce2); padding: 12px 0; }
.contract-revision pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
</style>
