<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { matchesRecordQuery } from '../../../utils/workspace-records'
import { submitCreateDialog } from '../../../utils/create-dialog'
import type { CustomerDuplicateCandidate } from '../../../../../shared/erp-api'

// 客户资料与订单共用服务端快照和草稿，切换页面无需另建业务状态。
const store = usePiniaAppStore()
const { busy, error, notice, connectionLost, customers, customerForm } = storeToRefs(store)
const { can, createCustomer } = store
const customerOpen = ref(false)
const customerQuery = ref('')
const checkingCandidates = ref(false)
const checkedName = ref('')
const duplicateCandidates = ref<CustomerDuplicateCandidate[]>([])
const candidateError = ref('')
watch(() => customerForm.value.name, () => {
  checkedName.value = ''
  duplicateCandidates.value = []
  candidateError.value = ''
})
const customerColumns = [
  { key: 'id', title: '编号', width: '120' },
  { key: 'name', title: '客户名称' }
]
const filteredCustomers = computed(() =>
  customers.value.filter((item) => matchesRecordQuery(customerQuery.value, [item.id, item.name]))
)
async function submitCustomer(): Promise<void> {
  // 断线或权限变化时不提交；服务端拒绝保存后仍保留弹窗和输入内容。
  if (connectionLost.value || !can('customer.manage') || checkingCandidates.value) return
  const name = customerForm.value.name.trim()
  if (name && checkedName.value !== name) {
    if (!window.nexora) {
      candidateError.value = '无法连接服务端，请稍后重试。'
      return
    }
    checkingCandidates.value = true
    candidateError.value = ''
    try {
      const result = await window.nexora.callApi('customerDuplicateCandidates', { name })
      // 查询期间若草稿变化，旧候选不能授权提交新名称。
      if (customerForm.value.name.trim() !== name) return
      duplicateCandidates.value = result
      checkedName.value = name
      if (result.length) return
    } catch {
      candidateError.value = '相似客户查询失败，请重试。'
      return
    } finally {
      checkingCandidates.value = false
    }
  }
  await submitCreateDialog(createCustomer, { busy, error, notice }, customerOpen)
}
</script>

<template>
  <section class="stack">
    <!-- 主标题由工作台提供，客户列表独立于销售单据。 -->
    <WorkspaceTable
      :show-title="false"
      title="客户资料"
      :columns="customerColumns"
      :data="filteredCustomers"
      :min-table-width="480"
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
            <label>
              客户名称
              <AppInput
                v-model.trim="customerForm.name"
                required
                maxlength="120"
                placeholder="输入客户名称"
              />
            </label>
            <div v-if="duplicateCandidates.length" role="status" class="stack">
              <strong>发现相似客户，请核对后再新增：</strong>
              <span v-for="candidate in duplicateCandidates" :key="candidate.id">
                #{{ candidate.id }} {{ candidate.name }}（{{ candidate.match === 'same_name' ? '名称相同' : '名称相近' }}）
              </span>
              <span>如确认是不同客户，可再次提交。此操作不会合并现有资料。</span>
            </div>
            <span v-if="candidateError" role="alert">{{ candidateError }}</span>
            <AppButton type="submit" :disabled="busy || connectionLost || checkingCandidates" variant="primary"
              >{{ checkingCandidates ? '正在核对客户' : duplicateCandidates.length ? '仍要添加客户' : '添加客户' }}</AppButton
            >
          </form>
        </NModal>
      </template>
      <template #empty>{{ customerQuery ? '没有匹配的客户。' : '暂无客户，请先新增。' }}</template>
    </WorkspaceTable>
  </section>
</template>
