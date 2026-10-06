<script setup lang="ts">
// 来源单号由授权后的服务端响应提供，固定金额证据不作改写。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type { BusinessJournalEvidence, BusinessJournalMapping, LedgerAccount } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { businessRoleRows } from './business-journal-display'
const props = defineProps<{ source: BusinessJournalEvidence; mapping?: BusinessJournalMapping; accounts?: LedgerAccount[] }>()
const roles = computed(() => businessRoleRows(props.source).map(row => {
  const id = props.mapping?.[row.role]
  const account = props.accounts?.find(item => item.id === id)
  return { ...row, account: account ? `${account.code} · ${account.name}` : id ? `科目 #${id}` : '未配置' }
}))
const roleColumns = [{ key: 'label', title: '入账用途' }, { key: 'account', title: '映射科目' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const movementColumns = [{ key: 'id', title: '流水号' }, { key: 'material', title: '物料' }, { key: 'warehouse', title: '仓库' }, { key: 'quantity', title: '数量' }, { key: 'accounting_amount', title: '库存入账金额（元）' }]
const tradeColumns = [{ key: 'order_id', title: '订单号' }, { key: 'source_line_id', title: '单据明细号' }, { key: 'quantity', title: '数量' }, { key: 'unit_price', title: '订单单价' }, { key: 'amount', title: '往来金额（元）' }]
const recordColumns = [{ key: 'id', title: '记录号' }, { key: 'reference', title: '依据编号' }, { key: 'kind', title: '类别' }, { key: 'amount', title: '金额（元）' }, { key: 'note', title: '备注 / 原因' }]
</script>

<template>
  <div class="stack business-evidence">
    <p>{{ source.label }} {{ relatedDocumentLabel(source, 'source') }} · 发生日期 {{ source.source_date }}（UTC）</p>
    <p v-for="warning in source.warnings" :key="warning" class="muted">{{ warning }}</p>
    <p v-for="blocker in source.blockers" :key="blocker" role="alert">{{ blocker }}</p>
    <WorkspaceTable title="来源入账金额" :columns="roleColumns" :data="roles" :min-table-width="630" />
    <NCollapse><AppCollapseItem v-if="source.movements.length" name="movements" :title="`库存流水依据（${source.movements.length} 笔）`">
      <WorkspaceTable title="库存流水" :columns="movementColumns" :data="source.movements" :min-table-width="850">
        <template #cell-material="{ row }">{{ source.labels[`material:${row.material_id}`] || `物料 #${row.material_id}` }}</template>
        <template #cell-warehouse="{ row }">{{ source.labels[`warehouse:${row.warehouse_id}`] || `仓库 #${row.warehouse_id}` }}</template>
        <template #cell-accounting_amount="{ row }">{{ row.accounting_amount ?? '待核价' }}</template>
      </WorkspaceTable>
    </AppCollapseItem>
    <AppCollapseItem v-if="source.business.length" name="business" :title="`订单金额依据（${source.business.length} 笔）`">
      <WorkspaceTable title="往来原始单据" :columns="tradeColumns" :data="source.business" :min-table-width="650">
        <template #cell-unit_price="{ row }">{{ row.unit_price ?? '未定价' }}</template><template #cell-amount="{ row }">{{ row.amount ?? '未定价' }}</template>
      </WorkspaceTable>
    </AppCollapseItem>
    <AppCollapseItem v-if="source.records.length" name="records" :title="`登记记录（${source.records.length} 笔）`">
      <WorkspaceTable title="原始登记" :columns="recordColumns" :data="source.records" :min-table-width="700">
        <template #cell-kind="{ row }">{{ ({ receivable: '应收', payable: '应付', labor: '人工费用', overhead: '制造费用' } as Record<string, string>)[String(row.kind)] ?? (row.entry_id ? `冲销成本 #${row.entry_id}` : '—') }}</template>
        <template #cell-note="{ row }">{{ row.note || row.reason || '—' }}</template>
      </WorkspaceTable>
    </AppCollapseItem></NCollapse>
  </div>
</template>

<style scoped>
.business-evidence :deep(.vxe-table--viewport-wrapper) { overflow: clip; }
</style>
