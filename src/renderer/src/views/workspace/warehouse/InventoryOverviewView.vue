<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { useAppStore } from '../../../store/app-store'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  busy,
  materials,
  stock,
  stockSummary,
  movements,
  receipts,
  warehouses,
  selectedWarehouseId,
  refreshData,
  perform
} = useAppStore()
// 当前库存统一使用公共表格，数量列保留业务单位。
const columns = [{ key: 'sku', title: '物料编码' }, { key: 'name', title: '物料名称' }, { key: 'quantity', title: '数量' }]
</script>

<template>
  <section class="stack">
    <WorkspaceTable dataset="stock" :query-filters="{ warehouse_id: selectedWarehouseId || null }" :show-title="false" title="库存总览" :columns="columns" :data="stock">
      <template #filters>
        <label
          >仓库<WorkspaceSelect remote-dataset="warehouses"
            v-model="selectedWarehouseId"
            :disabled="busy"
            @change="perform(refreshData, '库存已切换。')"
            :options="[
              { label: '全部仓库', value: 0 },
              ...warehouses.map((item) => ({ label: item.name, value: item.id }))
            ]"
        /></label>
        <AppButton
          :disabled="busy"
          @click="perform(refreshData, '数据已刷新。')"
          variant="primary"
          type="button"
          >刷新库存</AppButton
        >
      </template>
      <template #beforeTable>
        <div class="summary-grid">
          <div class="metric">
            <span>物料种类</span><strong>{{ stockSummary.material_count }}</strong>
          </div>
          <div class="metric">
            <span>已确认入库单</span
            ><strong>{{ stockSummary.posted_receipt_count }}</strong>
          </div>
          <div class="metric">
            <span>库存流水</span><strong>{{ stockSummary.movement_count }}</strong>
          </div>
        </div>
      </template>
      <template #cell-quantity="{ row }"
        ><strong>{{ row.quantity }}</strong> {{ row.unit }}</template
      >
      <template #empty>暂无物料，先到基础资料中添加。</template>
    </WorkspaceTable>
  </section>
</template>
