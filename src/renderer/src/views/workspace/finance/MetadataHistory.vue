<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { onMounted, ref } from 'vue'
import type {
  AccountingPeriod,
  FinanceMetadataChange,
  LedgerAccount
} from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { displayError, localTime } from '../../../utils/formatters'

type Change = FinanceMetadataChange<LedgerAccount | AccountingPeriod>
const props = defineProps<{ recordId?: number; dataset?: 'ledgerAccountHistory' | 'periodHistory'; load: () => Promise<Change[]> }>()
const rows = ref<Change[]>([])
const loading = ref(false)
const error = ref('')
const columns = [
  { key: 'created_at', title: '时间' }, { key: 'changed_by_name', title: '操作者' },
  { key: 'changes', title: '变更' }, { key: 'reason', title: '依据 / 原因' }
]
async function reload(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = ''
  rows.value = []
  try { rows.value = await props.load() }
  catch (cause) { error.value = displayError(cause) }
  finally { loading.value = false }
}
function description(item: Change): string {
  const { before, after } = item
  if (!before) return `建立 ${after.code} · ${after.name}（版本 ${after.version}）`
  const parts: string[] = []
  if (before.name !== after.name) parts.push(`名称：${before.name} → ${after.name}`)
  if ('status' in before && 'status' in after && before.status !== after.status)
    parts.push(after.status === 'closed' ? '结账期间' : '重开期间')
  if ('is_active' in before && 'is_active' in after && before.is_active !== after.is_active)
    parts.push(after.is_active ? '启用科目' : '停用科目')
  return `${parts.join('；')}（版本 ${before.version} → ${after.version}）`
}
onMounted(() => { if (!props.recordId) void reload() })
</script>

<template>
  <WorkspaceTable :dataset="recordId ? dataset : undefined" :query-filters="dataset === 'ledgerAccountHistory' ? { account_id: recordId || null } : { period_id: recordId || null }"
    title="资料变更记录"
    :show-title="false"
    :columns="columns"
    :data="rows"
    :error="error"
    :min-table-width="720"
  >
    <template #errorActions
      ><AppButton :disabled="loading" @click="reload" variant="secondary" type="button"
        >重新读取</AppButton
      ></template
    >
    <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
    <template #cell-changes="{ row }">{{ description(row) }}</template>
    <template #empty>{{ loading ? '正在读取变更记录…' : '暂无变更记录。' }}</template>
  </WorkspaceTable>
</template>
