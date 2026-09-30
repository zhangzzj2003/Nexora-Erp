<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { onMounted, ref } from 'vue'
import type { OpeningBalanceChange } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { displayError, localTime } from '../../../utils/formatters'
import { openingActionLabels, openingStatusLabels } from './opening-display'
const props = defineProps<{ snapshotId?: string; snapshotPath?: string; recordId?: number; load: () => Promise<OpeningBalanceChange[]> }>()
const rows = ref<OpeningBalanceChange[]>([])
const loading = ref(false)
const error = ref('')
const columns = [
  { key: 'created_at', title: '时间', width: '180' },
  { key: 'changed_by_name', title: '操作者', width: '110' },
  { key: 'action', title: '操作', width: '110' },
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
onMounted(() => { if (!props.recordId && !props.snapshotId) void reload() })
</script>
<template>
  <WorkspaceTable :snapshot-id="snapshotId" :snapshot-path="snapshotPath" :dataset="recordId ? 'openingHistory' : undefined" :query-filters="{ opening_balance_id: recordId || null }"
    title="期初操作记录"
    :show-title="false"
    :data="rows"
    :columns="columns"
    :error="error"
    :min-table-width="940"
  >
    <template #errorActions
      ><AppButton :disabled="loading" @click="reload" variant="secondary" type="button"
        >重新读取</AppButton
      ></template
    >
    <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
    <template #cell-action="{ row }">{{
      openingActionLabels[row.action as keyof typeof openingActionLabels]
    }}</template>
    <template #cell-after="{ row }"
      ><div>
        {{ openingStatusLabels[row.after.status as keyof typeof openingStatusLabels] }} · 版本
        {{ row.after.version }}
      </div>
      <div>
        借贷各 <span class="journal-amount">¥{{ row.after.total_debit }}</span>
      </div>
      <div>{{ row.after.reference }} · {{ row.after.effective_date }}</div></template
    >
    <template #empty>{{ loading ? '正在读取操作记录…' : '暂无记录。' }}</template>
  </WorkspaceTable>
</template>
