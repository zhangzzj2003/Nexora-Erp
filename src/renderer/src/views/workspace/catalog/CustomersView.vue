<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import CustomerFields from './CustomerFields.vue'
import type { Customer } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { matchesRecordQuery } from '../../../utils/workspace-records'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 客户资料与订单共用服务端快照和草稿，切换页面无需另建业务状态。
const store = usePiniaAppStore()
const { busy, error, notice, connectionLost, customers, customerForm, customerEdit, customerHistory, users, user } = storeToRefs(store)
const { can, createCustomer, updateCustomer, loadCustomerHistory } = store
const customerOpen = ref(false)
const customerQuery = ref('')
const historyOpen = ref(false)
const historyCustomerId = ref(0)
const admin = computed(() => user.value?.roles.includes('admin') ?? false)
// 只用页面可见的档案填充草稿，转交必须由服务端再次检查管理员和版本。
function editCustomer(row: Customer): void {
  customerEdit.value = { ...row, is_active: Boolean(row.is_active), reason: '' }
}
// 新增联系人与归属列后保留可读列宽，窄窗口通过公共横向滚动浏览。
const customerColumns = [
  { key: 'id', title: '编号', width: '80' },
  { key: 'name', width: '180', title: '客户名称' },
  { key: 'owner_name', width: '120', title: '负责商务' },
  { key: 'contact_name', width: '140', title: '联系人' },
  { key: 'phone', width: '160', title: '联系电话' },
  { key: 'address', width: '220', title: '地址' },
  { key: 'status', width: '80', title: '状态' },
  { key: 'actions', title: '操作', width: '200' }
]
const filteredCustomers = computed(() =>
  customers.value.filter((item) => matchesRecordQuery(customerQuery.value, [item.id, item.name, item.owner_name, item.contact_name, item.phone]))
)
async function submitCustomer(): Promise<void> {
  // 断线或权限变化时不提交；服务端拒绝保存后仍保留弹窗和输入内容。
  if (connectionLost.value || !can('customer.manage')) return
  await submitCreateDialog(createCustomer, { busy, error, notice }, customerOpen)
}
</script>

<template>
  <section class="stack">
    <!-- 主标题由工作台提供，客户列表独立于销售单据。 -->
    <WorkspaceTable dataset="customers" :query="customerQuery"
      :show-title="false"
      title="客户资料"
      :columns="customerColumns"
      :data="filteredCustomers"
      :min-table-width="1200"
    >
      <template #actions>
        <AppButton
          v-if="can('customer.manage')"
          type="button"
          :disabled="busy || connectionLost"
          @click="customerOpen = true"
          variant="primary"
        >
          新增客户
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索客户
          <AppInput v-model="customerQuery" placeholder="输入编号或名称" />
        </label>
      </template>
      <template #beforeTable>
        <NModal
          v-if="can('customer.manage')"
          v-model:show="customerOpen"
          preset="card"
          title="新增客户"
          :mask-closable="!busy"
          :style="{ width: 'min(560px, calc(100vw - 32px))' }"
        >
          <form class="inline-form" @submit.prevent="submitCustomer">
            <CustomerFields v-model="customerForm" :admin="admin" :users="users || []" :disabled="busy" />
            <AppButton type="submit" :disabled="busy || connectionLost" variant="primary"
              >添加客户</AppButton
            >
          </form>
        </NModal>
      </template>
      <!-- 修改失败保留草稿；已引用客户通过停用处理，保留业务追溯。 -->
      <template #cell-status="{ row }">{{ row.is_active ? '启用' : '停用' }}</template>
      <template #cell-actions="{ row }">
        <AppButton v-if="can('customer.manage')" :disabled="busy || connectionLost" @click="editCustomer(row)" size="small">编辑 / 转交</AppButton>
        <AppButton :disabled="busy || connectionLost" @click="historyCustomerId = row.id; historyOpen = true" size="small">修改记录</AppButton>
      </template>
      <template #empty>{{ customerQuery ? '没有匹配的客户。' : '暂无客户，请先新增。' }}</template>
    </WorkspaceTable>
    <NModal :show="customerEdit !== null" @update:show="value => { if (!value && !busy) customerEdit = null }" preset="card" title="编辑客户资料" :mask-closable="!busy" :style="{ width: 'min(680px, calc(100vw - 32px))' }">
      <form v-if="customerEdit" class="inline-form" @submit.prevent="updateCustomer">
        <CustomerFields v-model="customerEdit" :admin="admin" :users="users || []" :disabled="busy" />
        <label>修改原因<AppInput v-model.trim="customerEdit.reason" required maxlength="200" /></label>
        <p class="muted">转交客户不会改变历史订单负责商务；订单可由管理员独立移交。</p>
        <AppButton type="submit" :disabled="busy || connectionLost" variant="primary">保存修改</AppButton>
      </form>
    </NModal>
    <NModal v-model:show="historyOpen" preset="card" title="客户修改记录" :style="{ width: 'min(860px, calc(100vw - 32px))' }">
      <WorkspaceTable v-if="historyCustomerId" dataset="customerHistory" :query-filters="{ customer_id: historyCustomerId }" title="修改记录" :data="customerHistory" :columns="[{key:'action',title:'操作'},{key:'reason',title:'原因'},{key:'changed_by',title:'操作人编号'},{key:'created_at',title:'时间'}]" />
    </NModal>

  </section>
</template>
