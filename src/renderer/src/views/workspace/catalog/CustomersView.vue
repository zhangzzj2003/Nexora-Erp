<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NUpload, NCheckbox } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { matchesRecordQuery } from '../../../utils/workspace-records'
import { submitCreateDialog } from '../../../utils/create-dialog'
import type { CustomerDuplicateCandidate, CustomerImportPreview } from '../../../../../shared/erp-api'
import { parseCustomerCsv } from './customer-import'

// 客户资料与订单共用服务端快照和草稿，切换页面无需另建业务状态。
const store = usePiniaAppStore()
const { busy, error, notice, connectionLost, customers, customerForm, user } = storeToRefs(store)
const { can, createCustomer } = store
const customerOpen = ref(false)
const customerQuery = ref('')
const checkingCandidates = ref(false)
const checkedName = ref('')
const duplicateCandidates = ref<CustomerDuplicateCandidate[]>([])
const candidateError = ref('')
const importOpen = ref(false)
const importBusy = ref(false)
const importNames = ref<string[]>([])
const importPreview = ref<CustomerImportPreview | null>(null)
const importReason = ref('')
const allowSimilar = ref(false)
const importError = ref('')
let importRevision = 0
function clearImport(): void {
  importRevision += 1
  importBusy.value = false
  importNames.value = []
  importPreview.value = null
  importReason.value = ''
  allowSimilar.value = false
  importError.value = ''
}
watch(importOpen, open => { if (!open) clearImport() })
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
  importOpen.value = false
  clearImport()
})
watch(connectionLost, lost => { if (lost) { importOpen.value = false; clearImport() } })
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

async function selectImportFile(data: { file: { file?: File | null } }): Promise<void> {
  const file = data.file.file
  clearImport()
  if (!file) return
  const revision = importRevision
  if (file.size > 256 * 1024) {
    importError.value = 'CSV 文件不能超过 256 KiB。'
    return
  }
  importBusy.value = true
  try {
    const names = parseCustomerCsv(await file.text())
    if (!window.nexora) throw new Error('无法连接服务端')
    const preview = await window.nexora.callApi('customerImportPreview', { names })
    if (revision !== importRevision || !importOpen.value) return
    importNames.value = names
    importPreview.value = preview
  } catch (cause) {
    if (revision === importRevision) importError.value = store.displayError(cause)
  } finally {
    if (revision === importRevision) importBusy.value = false
  }
}

async function submitImport(): Promise<void> {
  if (busy.value || importBusy.value || connectionLost.value || !can('customer.manage')
    || !importPreview.value?.can_import || !importReason.value.trim()
    || (importPreview.value.requires_confirmation && !allowSimilar.value)) return
  importError.value = ''
  const actorId = user.value?.id
  const result = await store.importCustomerNames(
    [...importNames.value], importReason.value.trim(), allowSimilar.value)
  if (actorId !== user.value?.id) return
  if (result) importOpen.value = false
  else importError.value = error.value || '导入失败，请重试。'
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
          @click="importOpen = true"
        >导入客户 CSV</AppButton>
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
          v-model:show="importOpen"
          preset="card"
          title="导入客户 CSV"
          :mask-closable="!importBusy && !busy"
          :closable="!importBusy && !busy"
          :style="{ width: 'min(720px, calc(100vw - 32px))' }"
        >
          <div class="stack">
            <p>仅导入 UTF-8 单列客户名称，首行为“客户名称”或 name；每次 1 至 100 位。导入后默认由当前账号负责。</p>
            <NUpload accept=".csv,text/csv" :default-upload="false" :show-file-list="false"
              :file-list="[]" :disabled="importBusy || connectionLost" @change="selectImportFile">
              <AppButton type="button" :disabled="importBusy || connectionLost">选择 CSV 文件</AppButton>
            </NUpload>
            <p v-if="importBusy" role="status">正在检查客户资料…</p>
            <p v-if="importError" role="alert">{{ importError }}</p>
            <template v-if="importPreview">
              <p>{{ importPreview.rows.length }} 条待导入；{{ importPreview.can_import ? '可提交' : '含同名客户，须修改文件后重试' }}。</p>
              <ol style="max-height: 280px; overflow: auto">
                <li v-for="row in importPreview.rows" :key="row.row">
                  {{ row.name }}：{{ !row.can_import ? '已有同名客户' : row.requires_confirmation ? '有相似候选' : '可导入' }}
                  <span v-for="candidate in row.candidates" :key="candidate.id">
                    ；#{{ candidate.id }} {{ candidate.name }}（{{ candidate.match === 'same_name' ? '同名' : '相近' }}）
                  </span>
                  <span v-if="row.batch_candidates.length">；与本批第 {{ row.batch_candidates.join('、') }} 条相近</span>
                </li>
              </ol>
              <label>导入依据
                <AppInput v-model.trim="importReason" maxlength="200" placeholder="填写资料来源或核对依据" />
              </label>
              <NCheckbox v-if="importPreview.requires_confirmation" v-model:checked="allowSimilar">
                我已核对相似名称，确认导入不同客户
              </NCheckbox>
              <AppButton type="button" variant="primary"
                :disabled="importBusy || busy || connectionLost || !importPreview.can_import || !importReason.trim() || (importPreview.requires_confirmation && !allowSimilar)"
                @click="submitImport">确认导入</AppButton>
            </template>
          </div>
        </NModal>
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
