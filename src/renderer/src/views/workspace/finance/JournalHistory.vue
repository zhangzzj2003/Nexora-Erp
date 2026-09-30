<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { onMounted, ref } from 'vue'
import type { JournalChange } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { displayError, localTime } from '../../../utils/formatters'
import { journalActionLabels, journalStatusLabels } from './journal-display'

const props = defineProps<{ recordId?: number; load: () => Promise<JournalChange[]> }>()
const rows = ref<JournalChange[]>([])
const loading = ref(false)
const error = ref('')
const columns = [
  { key: 'created_at', title: '时间', width: '180' },
  { key: 'changed_by_name', title: '操作者', width: '110' },
  { key: 'action', title: '操作', width: '90' },
  { key: 'after', title: '结果', width: '330' },
  { key: 'reason', title: '原因', width: '210' }
]
async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  rows.value = []
  try {
    rows.value = await props.load()
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    loading.value = false
  }
}
onMounted(() => { if (!props.recordId) void reload() })
</script>

<template>
  <WorkspaceTable :dataset="recordId ? 'journalHistory' : undefined" :query-filters="{ journal_id: recordId || null }"
    title="凭证操作记录"
    :show-title="false"
    :data="rows"
    :columns="columns"
    :error="error"
    :min-table-width="920"
  >
    <template #errorActions
      ><AppButton :disabled="loading" @click="reload" variant="secondary" type="button"
        >重新读取</AppButton
      ></template
    >
    <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
    <template #cell-action="{ row }">{{
      journalActionLabels[row.action as keyof typeof journalActionLabels]
    }}</template>
    <template #cell-after="{ row }"
      ><div>
        {{ journalStatusLabels[row.after.status as keyof typeof journalStatusLabels] }} · 版本
        {{ row.after.version }}
      </div>
      <div>
        借贷各 <span class="journal-amount">¥{{ row.after.total_debit }}</span>
      </div>
      <div>{{ row.after.reference }} · {{ row.after.journal_date }}</div></template
    >
    <template #empty>{{ loading ? '正在读取操作记录…' : '暂无记录。' }}</template>
  </WorkspaceTable>
</template>
