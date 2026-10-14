<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'

// 总览的查询草稿和页码保存在 Pinia，页面只接收服务端当前页。
const store = usePiniaAppStore()
const { warehouses, connectionLost, stockOverviewQuery, stockOverviewResult,
  stockOverviewLoading, stockOverviewError } = storeToRefs(store)
const { queryStockOverview } = store
onMounted(() => { void queryStockOverview() })
// 当前库存统一使用公共表格，数量列保留业务单位。
const columns = [{ key: 'sku', title: '物料编码' }, { key: 'name', title: '物料名称' }, { key: 'quantity', title: '数量' }]
</script>

<template>
  <section class="stack">
    <WorkspaceTable :show-title="false" title="库存总览" :columns="columns" :data="stockOverviewResult?.items ?? []"
      :loading="stockOverviewLoading" :error="stockOverviewError"
      :pagination="{ page: stockOverviewQuery.page, pageSize: stockOverviewQuery.page_size, total: stockOverviewResult?.total ?? 0, disabled: connectionLost }"
      @page-change="queryStockOverview">
      <template #filters>
        <label
          >仓库<WorkspaceSelect
            v-model="stockOverviewQuery.warehouse_id"
            :disabled="stockOverviewLoading || connectionLost"
            @change="queryStockOverview(1)"
            :options="[
              { label: '全部仓库', value: null },
              ...warehouses.map((item) => ({ label: item.name, value: item.id }))
            ]"
        /></label>
        <AppButton
          :disabled="stockOverviewLoading || connectionLost"
          @click="queryStockOverview()"
          variant="primary"
          type="button"
          >刷新库存</AppButton
        >
      </template>
      <template #beforeTable>
        <div v-if="stockOverviewResult && !stockOverviewLoading && !stockOverviewError" class="summary-grid">
          <div class="metric">
            <span>物料种类</span><strong>{{ stockOverviewResult.summary.material_count }}</strong>
          </div>
          <div class="metric">
            <span>已确认入库单</span
            ><strong>{{ stockOverviewResult.summary.posted_receipt_count }}</strong>
          </div>
          <div class="metric">
            <span>库存流水</span><strong>{{ stockOverviewResult.summary.movement_count }}</strong>
          </div>
        </div>
      </template>
      <template #cell-quantity="{ row }"
        ><strong>{{ row.quantity }}</strong> {{ row.unit }}</template
      >
      <template #errorActions>
        <AppButton :disabled="stockOverviewLoading || connectionLost" @click="queryStockOverview()" variant="secondary" size="small">重新查询</AppButton>
      </template>
      <template #empty>暂无物料，先到基础资料中添加。</template>
    </WorkspaceTable>
  </section>
</template>
