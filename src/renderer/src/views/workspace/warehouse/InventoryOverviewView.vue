<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import InventoryDetailDialogs from '../../../components/workspace/InventoryDetailDialogs.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { isNegativeStock } from '../../../../../shared/stock-overview'
import type { WorkspaceSearchFilterField } from '../../../utils/workspace-search-filters'

// 总览按物料聚合；编号和查看按钮使用同一弹窗，关闭后保留筛选与页码。
const store = usePiniaAppStore()
const { warehouses, materialCategories, connectionLost, stockOverviewQuery: query,
  stockOverviewResult: result, stockOverviewLoading: loading, stockOverviewError: error } = storeToRefs(store)
const { queryStockOverview, resetStockOverview, openStockMaterial, closeLedgerMaterial } = store
const columns = [
  { key: 'sku', title: '物料编号', width: '160' }, { key: 'name', title: '物料名称', width: '260' },
  { key: 'category', title: '物料分类', width: '140' }, { key: 'quantity', title: '物料数量', width: '150', align: 'right' as const },
  { key: 'actions', title: '操作', width: '100' }
]
const filters = computed(() => ({ warehouse_id: query.value.warehouse_id, category_group: query.value.category_group ?? null }))
const fields = computed<WorkspaceSearchFilterField[]>(() => [
  { kind: 'select', key: 'warehouse_id', label: '仓库', options: [{ label: '全部仓库', value: null }, ...warehouses.value.map(item => ({ label: item.name, value: item.id }))] },
  { kind: 'select', key: 'category_group', label: '物料分类', options: [{ label: '全部分类', value: null }, { label: '未分类', value: '' },
    ...materialCategories.value.filter(item => !item.deleted).map(item => ({ label: item.name, value: item.code }))] }
])
let searchTimer: ReturnType<typeof setTimeout> | undefined
function search(value: string): void {
  query.value.keyword = value
  clearTimeout(searchTimer)
  // 关键词走服务端完整范围检索，连续输入合并请求，不在当前页里过滤。
  searchTimer = setTimeout(() => { void queryStockOverview(1) }, 250)
}
function updateFilters(value: typeof filters.value): void {
  clearTimeout(searchTimer)
  Object.assign(query.value, value)
  void queryStockOverview(1)
}
function reset(): void { clearTimeout(searchTimer); void resetStockOverview() }
onMounted(() => { void queryStockOverview() })
onUnmounted(() => { clearTimeout(searchTimer); closeLedgerMaterial() })
</script>

<template>
  <section class="stack">
    <WorkspaceTable :show-title="false" title="库存总览" :columns="columns" :data="result?.items ?? []" :min-table-width="810"
      :loading="loading" :error="error" :pagination="{ page: query.page, pageSize: query.page_size, total: result?.total ?? 0, disabled: connectionLost }"
      @page-change="queryStockOverview">
      <template #filters>
        <WorkspaceSearchFilters :query="query.keyword ?? ''" :filters="filters" :fields="fields" search-label="搜索物料"
          search-placeholder="物料编号或名称" :disabled="connectionLost"
          :reset-disabled="!query.keyword && query.warehouse_id === null && query.category_group == null"
          @update:query="search" @update:filters="updateFilters" @reset="reset" />
      </template>
      <template #filterActions><AppButton :disabled="loading || connectionLost" @click="queryStockOverview()" variant="primary">刷新库存</AppButton></template>
      <template #beforeTable>
        <template v-if="result && !loading && !error">
          <p class="stock-scope">{{ query.warehouse_id === null ? '全部仓库合计' : warehouses.find(item => item.id === query.warehouse_id)?.name }} · 当前筛选范围，统计不受分页影响</p>
          <div class="stock-summary">
            <div class="metric"><span>物料种类</span><strong>{{ result.summary.material_count }}</strong></div>
            <div class="metric"><span>有库存物料</span><strong>{{ result.summary.positive_material_count }}</strong></div>
            <div class="metric"><span>零库存物料</span><strong>{{ result.summary.zero_material_count }}</strong></div>
            <div class="metric"><span>负库存物料</span><strong :class="{ 'stock-negative': result.summary.negative_material_count > 0 }">{{ result.summary.negative_material_count }}</strong></div>
          </div>
        </template>
      </template>
      <template #cell-sku="{ row }"><AppButton variant="text" :disabled="connectionLost" :aria-label="`查看物料 ${row.sku} 的详情与库存`" @click="openStockMaterial(row)">{{ row.sku }}</AppButton></template>
      <template #cell-category="{ row }"><span :title="row.category_name">{{ row.category_group_name }}</span></template>
      <template #cell-quantity="{ row }"><strong class="stock-quantity" :class="{ 'stock-negative': isNegativeStock(row.quantity) }">{{ row.quantity }}</strong> {{ row.unit }}</template>
      <template #cell-actions="{ row }"><AppButton variant="text" :disabled="connectionLost" @click="openStockMaterial(row)">查看</AppButton></template>
      <template #errorActions><AppButton :disabled="loading || connectionLost" @click="queryStockOverview()">重新查询</AppButton></template>
      <template #empty>当前筛选范围内暂无物料，可调整搜索或分类条件。</template>
    </WorkspaceTable>
    <InventoryDetailDialogs />
  </section>
</template>

<style scoped>
/* 概览只统计物料种数，不把不同单位的库存数量混加成一个总数。 */
.stock-scope { color: var(--workspace-field-muted); font-size: 13px; margin: 0 0 12px; }
.stock-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 20px; }
.stock-summary .metric { padding: 16px 20px; }
.stock-summary .metric strong { font-size: 27px; }
.stock-negative { color: var(--app-danger, #b94438); }
.stock-quantity { font-variant-numeric: tabular-nums; }
@media (max-width: 1000px) { .stock-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
