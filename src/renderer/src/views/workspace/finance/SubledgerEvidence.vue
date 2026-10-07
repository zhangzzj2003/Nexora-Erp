<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import type { SubledgerOpening, SubledgerReconciliation, SubledgerChange } from '../../../../../shared/erp-api'
import { localTime } from '../../../utils/formatters'
import { auxiliaryText } from './auxiliary-display'
import { openingActionLabels, openingStatusLabels } from './opening-display'
import { subledgerKindLabels } from './subledger-display'

defineProps<{ record: SubledgerOpening; check: SubledgerReconciliation | null; changes: SubledgerChange[]; loading: boolean }>()
const comparisons = [{ key: 'account_id', title: '控制科目' }, { key: 'auxiliary', title: '完整辅助组合', width: '300' },
  { key: 'ledger_amount', title: '总账期初（元）' }, { key: 'subledger_amount', title: '分户合计（元）' }, { key: 'difference', title: '差额（元）' }]
const columns = [{ key: 'kind', title: '类别' }, { key: 'party_name', title: '往来快照', width: '200' },
  { key: 'document_reference', title: '原单编号' }, { key: 'document_date', title: '原单日期' },
  { key: 'account', title: '控制科目快照', width: '210' }, { key: 'auxiliary', title: '完整辅助快照', width: '300' },
  { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
function account(record: SubledgerOpening, id: number): string {
  const line = record.lines.find(item => item.account_id === id)
  return line ? `${line.account_code} · ${line.account_name}` : `科目 #${id}`
}
</script>

<template>
  <div class="ledger-editor">
    <p>{{ record.reference }} · {{ openingStatusLabels[record.status] }} · 版本 {{ record.version }} · 启用日 {{ record.effective_date }} · 人民币</p>
    <p>绑定总账期初 {{ relatedDocumentLabel(record, 'opening_balance') }}，版本 {{ record.opening_version }}。{{ record.note || '未填备注。' }}</p>
    <p v-if="loading" role="status">正在读取核对依据与审计记录…</p>
    <template v-if="check">
      <p role="status">{{ record.evidence ? '确认时已固定的核对证据' : '当前草稿核对' }}：{{ check.matched ? '全部组合一致' : '存在差额，须更正后提交' }}。同一对象的借贷余额按完整辅助组合净额勾稽。</p>
      <WorkspaceTable title="逐组合核对" :columns="comparisons" :data="check.rows" :min-table-width="900">
        <template #cell-account_id="{ row }">{{ account(record, row.account_id) }}</template>
        <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
        <template #empty>所选控制科目总账与分户均为零，没有需要核对的组合。</template>
      </WorkspaceTable>
    </template>
    <p v-else-if="!loading">此方案没有已确认的核对证据；取消或撤销后的记录只供历史追溯。</p>
    <WorkspaceTable title="原始未结单据" :columns="columns" :data="record.lines" :min-table-width="1350">
      <template #cell-kind="{ row }">{{ subledgerKindLabels[row.kind] }}</template>
      <template #cell-account="{ row }">{{ row.account_code }} · {{ row.account_name }}</template>
      <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
      <template #empty>此方案为空明细。</template>
    </WorkspaceTable>
    <h3>审计记录</h3>
    <NCollapse>
      <AppCollapseItem v-for="change in changes" :key="change.id" :name="change.id" :title="`${openingActionLabels[change.action]} · ${change.changed_by_name} · ${localTime(change.created_at)}`">
        <div class="ledger-editor">
          <p>依据：{{ change.reason }}。版本 {{ change.before?.version ?? '尚未建立' }} → {{ change.after.version }}；状态 {{ change.before ? openingStatusLabels[change.before.status] : '尚未建立' }} → {{ openingStatusLabels[change.after.status] }}。</p>
          <template v-for="side in (['before', 'after'] as const)" :key="side">
            <template v-if="change[side]">
              <p>{{ side === 'before' ? '变更前' : '变更后' }}：{{ change[side]!.reference }} · 总账 #{{ change[side]!.opening_balance_id }} / 版本 {{ change[side]!.opening_version }} · {{ change[side]!.effective_date }} · {{ change[side]!.note || '无备注' }}。</p>
              <p>控制范围：{{ change[side]!.control_accounts.map(item => `${subledgerKindLabels[item.kind]} 科目 #${item.account_id}`).join('；') }}</p>
              <WorkspaceTable :title="side === 'before' ? '变更前明细' : '变更后明细'" :columns="columns" :data="change[side]!.lines" :min-table-width="1350">
                <template #cell-kind="{ row }">{{ subledgerKindLabels[row.kind] }}</template>
                <template #cell-account="{ row }">{{ row.account_code }} · {{ row.account_name }}</template>
                <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
              </WorkspaceTable>
            </template>
          </template>
        </div>
      </AppCollapseItem>
    </NCollapse>
    <p v-if="!changes.length && !loading">暂无审计记录，请重新读取核对详情。</p>
  </div>
</template>
