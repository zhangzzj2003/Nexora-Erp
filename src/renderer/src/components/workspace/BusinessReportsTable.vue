<script setup lang="ts">
// 表格详情明确记录被点击的物料编号，返回时恢复到相同入口。
import { captureDialogOrigin } from '../../utils/dialog-origin'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField } from '../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from './WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from './WorkspaceMaterialSelect.vue'
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceTable from './WorkspaceTable.vue'
import { usePiniaAppStore } from '../../store/app-store'
import InventoryDetailDialogs from './InventoryDetailDialogs.vue'

const props = defineProps<{ domain: 'purchase' | 'inventory' }>()
const store = usePiniaAppStore()
const { busy, connectionLost, suppliers, warehouses, materials,
  purchaseReportQuery, inventoryReportQuery,
  purchaseReportResult, inventoryReportResult, inventoryReportLoading, inventoryReportExporting, inventoryReportError } = storeToRefs(store)
const { queryPurchaseReport, queryInventoryReport,
  exportPurchaseReport, exportInventoryReport } = store
const query = computed(() => props.domain === 'purchase' ? purchaseReportQuery.value : inventoryReportQuery.value)
const result = computed(() => props.domain === 'purchase' ? purchaseReportResult.value : inventoryReportResult.value)
// 报表列仍按服务端契约展示，仅为库存物料与仓库列提供可读的默认宽度。
const columns = computed(() => (result.value?.columns ?? []).map(column => props.domain === 'inventory'
  ? { ...column, width: ({ sku: '152', material_name: '290', warehouse: '100', unit: '80' } as Record<string, string>)[column.key] ?? '130' }
  : column))
const kinds = props.domain === 'purchase'
  ? [{ value: 'purchase_requests', label: '采购申请执行' },
    { value: 'purchase_orders', label: '采购订单执行' },
    { value: 'receiving_returns', label: '采购收退货' }]
  : [{ value: 'inventory_balance', label: '库存余额' },
    { value: 'stock_flow', label: '收发存' }]
const title = props.domain === 'purchase' ? '采购报表' : '库存报表'
const loading = computed(() => props.domain === 'purchase' ? busy.value : inventoryReportLoading.value || inventoryReportExporting.value)
// 库存分页只复用公共表格的页脚；采购报表保持原有完整查询行为。
const pagination = computed(() => props.domain === 'inventory' ? { page: inventoryReportQuery.value.page,
  pageSize: inventoryReportQuery.value.page_size, total: inventoryReportResult.value?.total ?? 0, disabled: connectionLost.value } : undefined)
const run = (): Promise<void> => props.domain === 'purchase' ? queryPurchaseReport() : queryInventoryReport()
const exportCsv = (): Promise<void> => props.domain === 'purchase' ? exportPurchaseReport() : exportInventoryReport()
// 库存筛选失效由 Pinia 同步处理，页码变化不能清空刚返回的分页快照。
if (props.domain === 'purchase') watch(purchaseReportQuery, () => {
  purchaseReportResult.value = null
}, { deep: true })
onMounted(() => { void (props.domain === 'inventory' ? queryInventoryReport(inventoryReportQuery.value.page) : run()) })
onUnmounted(() => { if (props.domain === 'inventory') store.closeLedgerMaterial() })
</script>

<template>
  <WorkspaceTable
    :show-title="false"
    :title="title"
    :columns="columns"
    :data="result?.rows ?? []"
    :loading="loading"
    :error="domain === 'inventory' ? inventoryReportError : ''"
    :pagination="pagination"
    @page-change="queryInventoryReport"
    :min-table-width="1050"
  >
    <template #actions>
      <AppButton
        :disabled="loading || connectionLost || !result"
        @click="exportCsv"
        :title="domain === 'inventory' ? '按当前筛选重新查询并导出全部记录' : undefined"
        variant="secondary"
        type="button"
        >导出 CSV</AppButton
      >
    </template>
    <template #filters>
      <label
        >报表<WorkspaceSelect
          v-model="query.kind"
          :options="[...kinds.map((item) => ({ label: item.label, value: item.value }))]"
      /></label>
      <label v-if="domain === 'purchase'"
        >供应商<WorkspaceSelect
          v-model="query.supplier_id"
          :options="[
            { label: '全部供应商', value: null },
            ...suppliers.map((item) => ({ label: item.name, value: item.id }))
          ]"
      /></label>
      <label v-if="domain === 'inventory' || query.kind === 'receiving_returns'"
        >仓库<WorkspaceSelect
          v-model="query.warehouse_id"
          :options="[
            { label: '全部仓库', value: null },
            ...warehouses.map((item) => ({ label: item.name, value: item.id }))
          ]"
      /></label>
      <label
        >物料<WorkspaceMaterialSelect :materials="materials"
          v-model="query.material_id"
          :options="[
            { label: '全部物料', value: null },
            ...materials.map((item) => ({
              label: (item.sku + ' · ' + item.name).trim(),
              value: item.id
            }))
          ]"
      /></label>
      <label v-if="query.kind !== 'inventory_balance'"
        >开始日期<NDatePicker
          to="body"
          :formatted-value="query.from_date || null"
          type="date"
          format="yyyy-MM-dd"
          value-format="yyyy-MM-dd"
          v-date-field="{ required: false }"
          @update:formatted-value="
            (value) => {
              query.from_date = datePickerString(value)
            }
          "
          clearable
      /></label>
      <label
        >{{ query.kind === 'inventory_balance' ? '截至日期' : '结束日期'
        }}<NDatePicker
          to="body"
          :formatted-value="query.to_date || null"
          type="date"
          format="yyyy-MM-dd"
          value-format="yyyy-MM-dd"
          v-date-field="{ required: false }"
          @update:formatted-value="
            (value) => {
              query.to_date = datePickerString(value)
            }
          "
          clearable
      /></label>
    </template>
    <template #filterActions
      ><AppButton :disabled="loading || connectionLost" @click="run" variant="primary" type="button"
        >查询</AppButton
      ></template
    >
    <template v-if="domain === 'inventory'" #errorActions>
      <AppButton :disabled="loading || connectionLost" @click="queryInventoryReport(inventoryReportQuery.page)" variant="secondary" size="small">重新查询</AppButton>
    </template>
    <template v-if="domain === 'inventory'" #cell-sku="{ row }">
      <AppButton variant="text" :disabled="connectionLost || !store.can('inventory.view')"
        :title="store.can('inventory.view') ? '查看物料详情与台账明细' : '需要库存查看权限'"
        :aria-label="`查看物料 ${row.sku} 的详情与台账`" @click.capture="captureDialogOrigin('inventory-material', $event)" @click="store.openReportMaterial(row)">{{ row.sku }}</AppButton>
    </template>
    <template #empty>筛选范围内暂无记录。</template>
  </WorkspaceTable>
  <InventoryDetailDialogs v-if="domain === 'inventory'" />
</template>
