<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'

// 来源页只展示已确认业务与审计信息，不在此登记收付款或修改历史金额。
const store = usePiniaAppStore()
const { receivablesPayables } = storeToRefs(store)
const { localTime, financialSource } = store
const sourceColumns = [
  { key: 'time', title: '确认时间' },
  { key: 'kind', title: '类别' },
  { key: 'party', title: '往来单位' },
  { key: 'source', title: '来源单据' },
  { key: 'material', title: '物料' },
  { key: 'amount', title: '金额变动' },
  { key: 'actor', title: '操作人' }
]

</script>

<template>
  <section v-if="receivablesPayables" class="stack">
    <WorkspaceTable
      :show-title="false"
      title="应收应付来源"
      :columns="sourceColumns"
      :data="receivablesPayables.entries"
      :min-table-width="980"
    >
      <template #beforeTable>
        <p class="muted">
          金额按已确认的出库、入库与退货明细计算，单位为人民币；无采购单价的历史入库显示“待核价”。
        </p>
      </template>
      <template #cell-time="{ row: item }">{{ localTime(item.posted_at) }}</template>
      <template #cell-kind="{ row: item }">
        {{ item.kind === 'receivable' ? '应收' : '应付' }}
      </template>
      <template #cell-party="{ row: item }">{{ item.party_name }}</template>
      <template #cell-source="{ row: item }">
        {{ financialSource(item) }}
        <small v-if="item.order_id">· 订单 {{ relatedDocumentLabel(item, 'order') }}</small>
      </template>
      <template #cell-material="{ row: item }">{{ item.sku }} × {{ item.quantity }}</template>
      <template #cell-amount="{ row: item }">
        {{ item.amount === null ? '待核价' : `¥${item.amount}` }}
      </template>
      <template #cell-actor="{ row: item }">
        {{ item.posted_by_name ?? (item.posted_by === null ? '未知' : `#${item.posted_by}`) }}
      </template>
      <template #empty>暂无已确认的金额来源单据。</template>
    </WorkspaceTable>
  </section>
</template>
