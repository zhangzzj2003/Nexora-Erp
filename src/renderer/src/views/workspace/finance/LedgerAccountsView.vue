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
import type { LedgerAccount } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import MetadataHistory from './MetadataHistory.vue'
import { ledgerCategoryLabels } from './ledger-metadata'
import './ledger-metadata.css'

const store = usePiniaAppStore()
const { busy, connectionLost, ledgerAccounts, ledgerAccountForm: form } = storeToRefs(store)
const { can, editLedgerAccount, saveLedgerAccount, loadLedgerAccountChanges } = store
const query = ref('')
const showForm = ref(false)
const history = ref<LedgerAccount | null>(null)
const filtered = computed(() =>
  ledgerAccounts.value.filter((item) =>
    [item.code, item.name, ledgerCategoryLabels[item.category]]
      .join(' ')
      .toLowerCase()
      .includes(query.value.trim().toLowerCase())
  )
)
const columns = [
  { key: 'code', title: '科目编码' },
  { key: 'name', title: '名称' },
  { key: 'category', title: '类别' },
  { key: 'normal_balance', title: '正常余额方向' },
  { key: 'is_active', title: '状态' },
  { key: 'version', title: '版本' },
  { key: 'actions', title: '操作' }
]
function edit(item?: LedgerAccount): void {
  editLedgerAccount(item)
  showForm.value = true
}
async function save(): Promise<void> {
  if (busy.value || connectionLost.value || !can('ledger_account.manage')) return
  if (await saveLedgerAccount()) showForm.value = false
}
</script>

<template>
  <section class="stack ledger-metadata-page">
    <WorkspaceTable dataset="ledgerAccounts" :query="query"
      title="总账科目"
      :show-title="false"
      :columns="columns"
      :data="filtered"
      :min-table-width="820"
    >
      <template #actions
        ><AppButton
          v-if="can('ledger_account.manage')"
          :disabled="busy || connectionLost"
          @click="edit()"
          variant="primary"
          type="button"
          >新增科目</AppButton
        ></template
      >
      <template #filters>
        <label class="ledger-search"
          >搜索科目<AppInput v-model="query" placeholder="输入编码、名称或类别"
        /></label>
        <span class="muted">共 {{ ledgerAccounts.length }} 个科目</span>
      </template>
      <template #cell-category="{ row }">{{
        ledgerCategoryLabels[row.category as keyof typeof ledgerCategoryLabels]
      }}</template>
      <template #cell-normal_balance="{ row }">{{
        row.normal_balance === 'debit' ? '借方' : '贷方'
      }}</template>
      <template #cell-is_active="{ row }">{{ row.is_active ? '启用' : '停用' }}</template>
      <template #cell-actions="{ row }">
        <div class="ledger-actions">
          <AppButton
            v-if="can('ledger_account.manage')"
            :disabled="busy || connectionLost"
            @click="edit(row)"
            variant="text"
            type="button"
            >编辑</AppButton
          >
          <AppButton :disabled="connectionLost" @click="history = row" variant="text" type="button"
            >变更记录</AppButton
          >
        </div>
      </template>
      <template #empty>{{
        query ? '没有匹配的科目。' : '暂无科目。请按公司的科目表新增。'
      }}</template>
    </WorkspaceTable>
    <NModal
      v-model:show="showForm"
      preset="card"
      :title="form.id === null ? '新增总账科目' : '编辑总账科目'"
      :mask-closable="!busy"
      :style="{
        width: 'min(760px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <form
        v-if="showForm && can('ledger_account.manage')"
        class="ledger-editor"
        @submit.prevent="save"
      >
        <p class="muted">编码、类别和正常余额方向保存后固定。名称与启停修改保留变更记录。</p>
        <div class="form-grid">
          <label
            >科目编码<AppInput
              v-model.trim="form.code"
              required
              maxlength="32"
              :disabled="form.id !== null"
              placeholder="例如 1001"
          /></label>
          <label>科目名称<AppInput v-model.trim="form.name" required maxlength="100" /></label>
          <label
            >类别<WorkspaceSelect
              v-model="form.category"
              :disabled="form.id !== null"
              :options="[
                ...Object.entries(ledgerCategoryLabels).map(([value, label]) => ({
                  label: label,
                  value
                }))
              ]"
          /></label>
          <label
            >正常余额方向<WorkspaceSelect
              v-model="form.normal_balance"
              :disabled="form.id !== null"
              :options="[
                { label: '借方', value: 'debit' },
                { label: '贷方', value: 'credit' }
              ]"
          /></label>
          <label v-if="form.id !== null"
            >科目状态<WorkspaceSelect
              v-model="form.is_active"
              :options="[
                { label: '启用', value: true },
                { label: '停用', value: false }
              ]"
          /></label>
          <label
            >建立依据 / 修改原因<AppInput
              v-model.trim="form.reason"
              required
              maxlength="200"
              placeholder="填写科目表依据或修改原因"
          /></label>
        </div>
        <div class="form-actions">
          <AppButton :disabled="busy || connectionLost" variant="primary" type="submit">{{
            busy ? '正在保存…' : '保存科目'
          }}</AppButton
          ><AppButton type="button" :disabled="busy" @click="showForm = false" variant="secondary"
            >取消</AppButton
          >
        </div>
      </form>
    </NModal>
    <NModal
      :show="history !== null"
      preset="card"
      :title="history ? `${history.code} · 变更记录` : '变更记录'"
      :style="{ width: 'min(1000px, calc(100vw - 32px))' }"
      @update:show="
        (value) => {
          if (!value) history = null
        }
      "
    >
      <MetadataHistory
        v-if="history"
        :key="history.id"
        :record-id="history!.id" dataset="ledgerAccountHistory" :load="() => loadLedgerAccountChanges(history!.id)"
      />
    </NModal>
  </section>
</template>
