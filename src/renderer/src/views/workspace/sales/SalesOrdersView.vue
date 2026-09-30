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
  connectionLost,
  materials,
  customers,
  salesOrders,
  users,
  user,
  salesForm,
  can,
  localTime,
  navigateToRoute,
  createSalesOrder,
  confirmSalesOrder,
  cancelSalesOrder,
  transferSalesOwner
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
// 订单独立转交，不借客户档案转交改变历史金额访问权限。
const transferDraft = ref<{ orderId: number; owner_id: number; version: number; reason: string } | null>(null)
async function saveTransfer(): Promise<void> {
  if (!transferDraft.value) return
  const draft = transferDraft.value
  await transferSalesOwner(draft.orderId, draft.owner_id, draft.version, draft.reason)
  if (!error.value) transferDraft.value = null
}
const createOpen = ref(false)
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
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.customer_name,
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
      v-if="can('sales_order.create')"
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
          <p class="eyebrow">SALES ORDER</p>
          <h2>新建销售订单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >客户<WorkspaceSelect
              v-model="salesForm.customer_id"
              required
              :options="[
                { label: '选择客户'.trim(), value: 0, disabled: true },
                ...customers.map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >参考单号（可选）<AppInput v-model.trim="salesForm.reference" maxlength="100"
          /></label>
        </div>
        <div class="form-actions">
          <span v-if="!customers.length" class="muted">暂无客户，请先建立客户资料。</span>
          <AppButton type="button" :disabled="busy" @click="openCustomers" variant="text">
            前往客户资料
          </AppButton>
          <span class="muted">订单草稿会保留，返回后可继续填写。</span>
        </div>
        <h3>销售明细</h3>
        <div v-for="(line, index) in salesForm.lines" :key="index" class="line-row">
          <label
            >物料<WorkspaceSelect
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
            >数量<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><label
            >单价（元）<AppInput
              v-model.trim="line.unit_price"
              type="number"
              min="0"
              max="1000000000"
              step="0.0001"
              required /></label
          ><AppButton
            type="button"
            :disabled="salesForm.lines.length === 1"
            @click="salesForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="
              salesForm.lines.push({
                material_id: 0,
                quantity: '1',
                unit_price: '0'
              })
            "
            variant="secondary"
          >
            添加明细</AppButton
          ><AppButton
            type="submit"
            :disabled="busy || !customers.length || !materials.length"
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
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
          <strong>#{{ item.id }} · {{ item.customer_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
            <span v-if="item.amount_visible">· 总额 ¥{{ item.total_amount }}</span><span v-else>· 金额无权限查看</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: '草稿',
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
            {{ line.unit }} <span v-if="item.amount_visible">· ¥{{ line.unit_price }}/{{ line.unit }}</span>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton v-if="user?.roles.includes('admin')" :disabled="busy" size="small" @click="transferDraft = { orderId: item.id, owner_id: item.owner_id || 0, version: item.owner_version, reason: '' }">转交商务</AppButton>

          <AppButton
            v-if="item.status === 'draft' && can('sales_order.confirm')"
            type="button"
            :disabled="busy"
            @click="confirmSalesOrder(item.id)"
            variant="primary"
            size="small"
          >
            确认订单
          </AppButton>
          <AppButton
            v-if="['draft', 'confirmed'].includes(item.status) && can('sales_order.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelSalesOrder(item.id)"
            variant="secondary"
            size="small"
          >
            取消订单
          </AppButton>
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

    <NModal :show="transferDraft !== null" @update:show="value => { if (!value && !busy) transferDraft = null }" preset="card" title="转交订单负责商务" :style="{ width: 'min(560px, calc(100vw - 32px))' }">
      <form v-if="transferDraft" class="inline-form" @submit.prevent="saveTransfer">
        <label>负责商务<WorkspaceSelect v-model="transferDraft.owner_id" :options="(users || []).filter(person => person.is_active).map(person => ({value: person.id, label: person.full_name || person.username}))" required /></label>
        <label>转交原因<AppInput v-model.trim="transferDraft.reason" required maxlength="200" /></label>
        <AppButton type="submit" variant="primary" :disabled="busy || connectionLost">确认转交</AppButton>
      </form>
    </NModal>
  </section>
</template>
