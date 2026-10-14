<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 日期直接使用 Naive UI，保持后端字符串格式以及原有必填和范围校验。
import { NDatePicker } from 'naive-ui'
import { datePickerString, vDateField } from '../../../utils/date-field'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { movementTypeLabels, movementTypeLabel } from '../../../utils/formatters'
import InventoryDetailDialogs from '../../../components/workspace/InventoryDetailDialogs.vue'
import { ledgerColumns as columns, ledgerTime } from '../../../utils/inventory-ledger-presentation'

const store = usePiniaAppStore()
const { connectionLost, warehouses, materials, ledgerQuery, ledgerResult, ledgerLoading, ledgerError } = storeToRefs(store)
const { queryLedger, openLedgerMaterial, openLedgerDocument, closeLedgerMaterial } = store
// 期初期末汇总同样通过公共表格展示，避免查询页保留第二种表格实现。
const groupColumns = [
  { key: 'sku', title: '物料编号', width: '152' }, { key: 'material_name', title: '物料名称', width: '250' },
  { key: 'warehouse_name', title: '仓库', width: '94' },
  { key: 'opening', title: '期初' }, { key: 'closing', title: '期末' }
]
const sourceOptions = Object.entries(movementTypeLabels)
// 首次进入沿用已选页；点击查询回到首页，翻页只请求目标页。
onMounted(() => { void queryLedger(ledgerQuery.value.page) })
// 离开台账即撤销详情请求，晚到的响应不能在其他页面重新打开窗口。
onUnmounted(closeLedgerMaterial)
</script>

<template>
  <section class="stack inventory-ledger-page">
    <WorkspaceTable
      :show-title="false"
      :data="ledgerResult.rows"
      title="库存台账"
      :columns="columns"
      :error="ledgerError"
      :loading="ledgerLoading"
      :pagination="{ page: ledgerQuery.page, pageSize: ledgerQuery.page_size, total: ledgerResult.total, disabled: connectionLost }"
      @page-change="queryLedger"
      :min-table-width="1240"
    >
      <template #filters>
        <label
          >仓库<WorkspaceSelect
            v-model="ledgerQuery.warehouse_id"
            :options="[
              { label: '全部仓库', value: null },
              ...warehouses.map((item) => ({ label: item.name, value: item.id }))
            ]"
        /></label>
        <label
          >物料<WorkspaceMaterialSelect :materials="materials"
            v-model="ledgerQuery.material_id"
            :options="[
              { label: '全部物料', value: null },
              ...materials.map((item) => ({
                label: (item.sku + ' · ' + item.name).trim(),
                value: item.id
              }))
            ]"
        /></label>
        <label
          >开始日期<NDatePicker
            to="body"
            :formatted-value="ledgerQuery.from_date || null"
            type="date"
            format="yyyy-MM-dd"
            value-format="yyyy-MM-dd"
            v-date-field="{ required: false }"
            @update:formatted-value="
              (value) => {
                ledgerQuery.from_date = datePickerString(value)
              }
            "
            clearable
        /></label>
        <label
          >结束日期<NDatePicker
            to="body"
            :formatted-value="ledgerQuery.to_date || null"
            type="date"
            format="yyyy-MM-dd"
            value-format="yyyy-MM-dd"
            v-date-field="{ required: false }"
            @update:formatted-value="
              (value) => {
                ledgerQuery.to_date = datePickerString(value)
              }
            "
            clearable
        /></label>
        <label
          >来源<WorkspaceSelect
            v-model="ledgerQuery.source_type"
            :options="[
              { label: '全部来源', value: null },
              ...sourceOptions.map(([key, label]) => ({ label: label, value: key }))
            ]"
        /></label>
      </template>
      <template #filterActions
        ><AppButton
          :disabled="ledgerLoading || connectionLost"
          @click="queryLedger()"
          variant="primary"
          type="button"
          >查询台账</AppButton
        ></template
      >
      <template #cell-sku="{ row }">
        <AppButton variant="text" :disabled="connectionLost" :aria-label="`查看物料 ${row.sku} 的详情与台账`"
          @click="openLedgerMaterial(row)">{{ row.sku }}</AppButton>
      </template>
      <template #cell-time="{ row }"><span class="ledger-time">{{ ledgerTime(row.created_at) }}</span></template>
      <template #cell-operator="{ row }">{{ row.created_by_name || '—' }}</template>
      <template #cell-source_type="{ row }">{{ movementTypeLabel(row.source_type) }}</template>
      <template #cell-source_document="{ row }">
        <AppButton variant="text" :disabled="connectionLost" :aria-label="`查看单据 ${relatedDocumentLabel(row, 'source')} 详情`"
          @click="openLedgerDocument(row)">{{ relatedDocumentLabel(row, 'source') }}</AppButton>
      </template>
      <template #cell-quantity="{ row: item }"
        >{{ item.quantity.startsWith('-') ? '' : '+' }}{{ item.quantity }} {{ item.unit }}</template
      >
      <template #cell-balance="{ row: item }">{{ item.balance_quantity }} {{ item.unit }}</template>
      <template #empty>
        <strong>筛选范围内暂无库存流水</strong>
        <span>可调整仓库、物料或日期后重新查询。</span>
      </template>
      <template #errorActions>
        <AppButton
          :disabled="ledgerLoading || connectionLost"
          @click="queryLedger(ledgerQuery.page)"
          variant="secondary"
          size="small"
          type="button"
          >重新查询</AppButton
        >
      </template>
    </WorkspaceTable>
    <!-- 先筛选再查看流水与汇总，避免期初期末把查询入口挤到页面下方。 -->
    <WorkspaceTable
      v-if="!ledgerLoading && !ledgerError && ledgerResult.groups.length"
      title="期初期末"
      :columns="groupColumns"
      :data="ledgerResult.groups"
      :min-table-width="680"
    >
      <template #cell-sku="{ row }"><AppButton variant="text" :disabled="connectionLost" @click="openLedgerMaterial(row)">{{ row.sku }}</AppButton></template>
      <template #cell-opening="{ row }">{{ row.opening_quantity }} {{ row.unit }}</template>
      <template #cell-closing="{ row }">{{ row.closing_quantity }} {{ row.unit }}</template>
    </WorkspaceTable>
    <InventoryDetailDialogs />
  </section>
</template>

<style scoped>
/* 固定时分格式便于纵向对齐，较窄窗口由公共表格横向滚动承载。 */
.ledger-time { white-space: nowrap; font-variant-numeric: tabular-nums; }
</style>
