import { computed, ref, type Ref } from 'vue'
import { matchesRecordQuery } from '../utils/workspace-records.ts'
import type { WorkspaceSearchFilterField } from '../utils/workspace-search-filters'
import type { WorkspaceSummaryFilterOption } from '../components/workspace/WorkspaceSummaryFilters.vue'

interface ProductionRecord {
  status: string
  warehouse_id: number
  warehouse_name: string
}
export interface ProductionStatusGroup {
  key: string
  label: string
  statuses: readonly string[]
  tone?: WorkspaceSummaryFilterOption['tone']
}

// 工单与完工页共用仓库的概览和筛选控件；只处理列表，不持有跨页面业务草稿。
export function useProductionRecords<T extends ProductionRecord>(
  records: Ref<T[]>,
  groups: readonly ProductionStatusGroup[],
  searchValues: (record: T) => readonly unknown[],
) {
  const recordQuery = ref('')
  const recordFilters = ref({ status: '', warehouse: 0 })
  const matching = computed(() => records.value.filter(record =>
    (!recordFilters.value.warehouse || record.warehouse_id === recordFilters.value.warehouse)
    && matchesRecordQuery(recordQuery.value, searchValues(record))))
  // 统计先应用关键词和仓库，再分组；切换状态不改变卡片基数，也不取表格当前页计数。
  const recordSummaries = computed<WorkspaceSummaryFilterOption[]>(() => [
    { key: '', label: '全部', count: matching.value.length, hint: '查看当前搜索及仓库范围的全部单据' },
    ...groups.map(group => ({ ...group, count: matching.value.filter(record => group.statuses.includes(record.status)).length,
      hint: `查看${group.label}单据` })),
  ])
  const filteredRecords = computed(() => matching.value.filter(record => !recordFilters.value.status
    || !!groups.find(group => group.key === recordFilters.value.status)?.statuses.includes(record.status)))
  const recordFilterFields = computed<WorkspaceSearchFilterField[]>(() => [
    { key: 'status', kind: 'select', label: '状态', options: [{ value: '', label: '全部状态' },
      ...groups.map(group => ({ value: group.key, label: group.label }))] },
    { key: 'warehouse', kind: 'select', label: '仓库', options: [{ value: 0, label: '全部仓库' },
      ...Array.from(new Map(records.value.map(record => [record.warehouse_id, { value: record.warehouse_id, label: record.warehouse_name }])).values())] },
  ])
  function resetRecordFilters(): void {
    recordQuery.value = ''
    recordFilters.value = { status: '', warehouse: 0 }
  }
  return { recordQuery, recordFilters, recordSummaries, recordFilterFields, filteredRecords, resetRecordFilters }
}
