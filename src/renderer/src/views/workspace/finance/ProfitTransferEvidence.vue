<script setup lang="ts">
// 凭证与来源保留内部 ID，界面优先显示服务端保存的业务单号。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import type { ProfitTransferEvidence } from '../../../../../shared/erp-api'
import { auxiliaryText } from './auxiliary-display'
import { journalTotals } from './journal-display'

const props = defineProps<{ evidence: ProfitTransferEvidence; canOpenJournal?: boolean }>()
const emit = defineEmits<{ openJournal: [id: number] }>()
const balances = [{ key: 'account', title: '损益科目' }, { key: 'balance', title: '待结余额（借正贷负，元）' },
  { key: 'auxiliary', title: '辅助组合' },
  { key: 'debit', title: '结转借方（元）' }, { key: 'credit', title: '结转贷方（元）' }]
const sources = [{ key: 'journal_id', title: '来源凭证' }, { key: 'journal_date', title: '日期' },
  { key: 'reference', title: '依据编号' }, { key: 'account_id', title: '科目编号' },
  { key: 'line_id', title: '分录号' }, { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const opening = [{ key: 'opening_balance_id', title: '正式期初来源' }, { key: 'account_id', title: '科目编号' },
  { key: 'line_id', title: '分录号' }, { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const excluded = [{ key: 'code', title: '科目编码' }, { key: 'name', title: '未纳管成本科目' }, { key: 'balance', title: '余额（借正贷负，元）' }]
const targetTotals = computed(() => journalTotals(props.evidence.lines.filter(item => item.account_id === props.evidence.target_account_id).map(item => ({ ...item, summary: '辅助转入' }))))
</script>

<template>
  <div class="stack profit-transfer-evidence">
    <p>{{ evidence.start_date }} 至 {{ evidence.end_date }} · 人民币 · UTC · 科目配置版本 {{ evidence.policy_version }}</p>
    <p>待结转净额：{{ evidence.net_profit }} 元（盈利为正，亏损为负）。这是累计待结余额，包含正式期初及历史已过账凭证，不能作为本期利润表。</p>
    <WorkspaceTable title="损益科目与清零分录" :columns="balances" :data="evidence.rows" :min-table-width="720">
      <template #cell-account="{ row }">{{ row.code }} · {{ row.name }}</template>
      <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
      <template #empty>纳管损益科目余额均为零。</template>
    </WorkspaceTable>
    <p v-if="evidence.target_account">转入 {{ evidence.target_account.code }} · {{ evidence.target_account.name }}：借方合计 {{ targetTotals.debit }} 元 / 贷方合计 {{ targetTotals.credit }} 元。按辅助组合分别转入；公司净额为零时仍可能有相抵的辅助分录。</p>
    <NCollapse>
      <AppCollapseItem name="source" :title="`已过账来源（${evidence.sources.length} 条分录）与正式期初`">
        <div class="stack">
          <WorkspaceTable title="损益凭证来源" :columns="sources" :data="evidence.sources" :min-table-width="1190">
            <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
            <template #cell-journal_id="{ row }"><AppButton v-if="canOpenJournal" variant="text" @click="emit('openJournal', row.journal_id)">{{ relatedDocumentLabel(row, 'journal') }}</AppButton><span v-else>{{ relatedDocumentLabel(row, 'journal') }}</span></template>
            <template #empty>没有损益已过账来源。</template>
          </WorkspaceTable>
          <WorkspaceTable title="正式期初来源" :columns="opening" :data="evidence.opening_sources" :min-table-width="930">
            <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
            <template #cell-opening_balance_id="{ row }">{{ relatedDocumentLabel(row, 'opening_balance') }}</template>
            <template #empty>没有纳入本次结转的正式期初损益余额。</template>
          </WorkspaceTable>
        </div>
      </AppCollapseItem>
      <AppCollapseItem v-if="evidence.excluded_cost_accounts.length" name="excluded" :title="`未纳管成本余额（${evidence.excluded_cost_accounts.length} 个科目）`">
        <p class="muted">这些科目保留余额，不参与本次结转。生产成本及在制品应按公司的成本核算规则处理。</p>
        <WorkspaceTable title="保留的成本余额" :columns="excluded" :data="evidence.excluded_cost_accounts" :min-table-width="640" />
      </AppCollapseItem>
    </NCollapse>
  </div>
</template>

<style scoped>
/* 外层面板和凭证弹窗共用证据；展开后由外层承接纵向滚动。 */
.profit-transfer-evidence { min-width: 0; grid-template-columns: minmax(0, 1fr); }
.profit-transfer-evidence :deep(.vxe-table--viewport-wrapper) { overflow: clip; }
</style>
