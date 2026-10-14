<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../app/AppButton.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { movementTypeLabel } from '../../utils/formatters'
import { relatedDocumentLabel } from '../../../../shared/document-numbering'
import { ledgerMovementColumns, ledgerTime } from '../../utils/inventory-ledger-presentation'

defineProps<{ overview?: boolean }>()
const store = usePiniaAppStore()
const { connectionLost, warehouses, ledgerMaterialQuery: query, ledgerMaterialResult: result,
  ledgerMaterialRowsLoading: rowsLoading, ledgerMaterialRowsError: rowsError } = storeToRefs(store)
// 台账筛选只作用于弹窗的独立查询，不改变总览数量及主表页码。
const warehouseOptions = computed(() => [{ label: '全部仓库', value: null },
  ...warehouses.value.map(row => ({ label: row.name, value: row.id }))])
const scope = computed(() => {
  if (!query.value) return ''
  const q = query.value
  const warehouse = q.warehouse_id === null ? '全部仓库' : warehouses.value.find(row => row.id === q.warehouse_id)?.name ?? '所选仓库'
  const dates = !q.from_date && !q.to_date ? '全部日期' : `${q.from_date || '最早'} 至 ${q.to_date || '至今'}`
  return `${warehouse} · ${dates} · ${q.source_type ? movementTypeLabel(q.source_type) : '全部来源'}`
})
</script>
<template>
  <p class="ledger-scope">{{ scope }}<small>按所选仓库、物料及日期核对流水</small></p>
  <WorkspaceTable v-if="query" title="物料台账明细" :data="result.rows" :columns="ledgerMovementColumns"
    :loading="rowsLoading" :error="rowsError" :min-table-width="898"
    :pagination="{ page: query.page, pageSize: query.page_size, total: result.total, disabled: connectionLost }"
    @page-change="store.queryLedgerMaterial">
    <template v-if="overview" #filters>
      <label>流水仓库<WorkspaceSelect :model-value="query.warehouse_id" :options="warehouseOptions"
        :disabled="connectionLost || rowsLoading" @update:model-value="store.selectStockMaterialWarehouse" /></label>
    </template>
    <template #cell-time="{ row }"><span class="ledger-time">{{ ledgerTime(row.created_at) }}</span></template>
    <template #cell-operator="{ row }">{{ row.created_by_name || '—' }}</template>
    <template #cell-source_type="{ row }">{{ movementTypeLabel(row.source_type) }}</template>
    <template #cell-source_document="{ row }"><AppButton variant="text" :disabled="connectionLost"
      :aria-label="`查看单据 ${relatedDocumentLabel(row, 'source')} 详情`" @click="store.openLedgerDocument(row)">{{ relatedDocumentLabel(row, 'source') }}</AppButton></template>
    <template #cell-quantity="{ row }">{{ row.quantity.startsWith('-') ? '' : '+' }}{{ row.quantity }} {{ row.unit }}</template>
    <template #cell-balance="{ row }">{{ row.balance_quantity }} {{ row.unit }}</template>
    <template #empty>当前范围内暂无该物料的库存流水。</template>
    <template #errorActions><AppButton :disabled="connectionLost || rowsLoading" @click="store.queryLedgerMaterial(query.page)">重新查询</AppButton></template>
    <template #footer v-if="!rowsLoading && !rowsError && result.groups.length">
      <!-- 使用服务端完整期间汇总，不用本页流水相加代替期初期末。 -->
      <div class="ledger-balances"><p v-for="group in result.groups" :key="group.warehouse_id">
        <strong>{{ group.warehouse_name }}</strong><span>期初 {{ group.opening_quantity }} {{ group.unit }}</span>
        <span>期末 {{ group.closing_quantity }} {{ group.unit }}</span>
      </p></div>
    </template>
  </WorkspaceTable>
</template>
<style scoped>
.ledger-scope { color: var(--workspace-field-muted); line-height: 1.7; }
.ledger-scope small { display: block; }
.ledger-time { white-space: nowrap; font-variant-numeric: tabular-nums; }
.ledger-balances p { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 8px 0; }
</style>
