<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField } from '../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from './WorkspaceSelect.vue'
import { computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceTable from './WorkspaceTable.vue'
import { usePiniaAppStore } from '../../store/app-store'

const props = defineProps<{ domain: 'purchase' | 'inventory' }>()
const store = usePiniaAppStore()
const { busy, connectionLost, suppliers, warehouses, materials,
  purchaseReportQuery, inventoryReportQuery,
  purchaseReportResult, inventoryReportResult } = storeToRefs(store)
const { queryPurchaseReport, queryInventoryReport,
  exportPurchaseReport, exportInventoryReport } = store
const query = computed(() => props.domain === 'purchase' ? purchaseReportQuery.value : inventoryReportQuery.value)
const result = computed(() => props.domain === 'purchase' ? purchaseReportResult.value : inventoryReportResult.value)
const kinds = props.domain === 'purchase'
  ? [{ value: 'purchase_requests', label: '采购申请执行' },
    { value: 'purchase_orders', label: '采购订单执行' },
    { value: 'receiving_returns', label: '采购收退货' }]
  : [{ value: 'inventory_balance', label: '库存余额' },
    { value: 'stock_flow', label: '收发存' }]
const title = props.domain === 'purchase' ? '采购报表' : '库存报表'
const run = (): Promise<void> => props.domain === 'purchase' ? queryPurchaseReport() : queryInventoryReport()
const exportCsv = (): Promise<void> => props.domain === 'purchase' ? exportPurchaseReport() : exportInventoryReport()
// 筛选变化后清除旧快照，避免用户把旧行误认为新条件的查询结果。
watch(query, () => {
  if (props.domain === 'purchase') purchaseReportResult.value = null
  else inventoryReportResult.value = null
}, { deep: true })
onMounted(() => { void run() })
</script>

<template>
  <WorkspaceTable :snapshot-id="result?.snapshot_id"
    :show-title="false"
    :title="title"
    :columns="result?.columns ?? []"
    :data="result?.rows ?? []"
    :loading="busy"
    :min-table-width="1050"
  >
    <template #actions>
      <AppButton
        :disabled="busy || connectionLost || !result"
        @click="exportCsv"
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
        >供应商<WorkspaceSelect remote-dataset="suppliers"
          v-model="query.supplier_id"
          :options="[
            { label: '全部供应商', value: null },
            ...suppliers.map((item) => ({ label: item.name, value: item.id }))
          ]"
      /></label>
      <label v-if="domain === 'inventory' || query.kind === 'receiving_returns'"
        >仓库<WorkspaceSelect remote-dataset="warehouses"
          v-model="query.warehouse_id"
          :options="[
            { label: '全部仓库', value: null },
            ...warehouses.map((item) => ({ label: item.name, value: item.id }))
          ]"
      /></label>
      <label
        >物料<WorkspaceSelect remote-dataset="materials"
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
      ><AppButton :disabled="busy || connectionLost" @click="run" variant="primary" type="button"
        >查询</AppButton
      ></template
    >
    <template #empty>筛选范围内暂无记录。</template>
  </WorkspaceTable>
</template>
