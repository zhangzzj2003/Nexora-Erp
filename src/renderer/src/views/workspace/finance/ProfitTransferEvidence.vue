<script setup lang="ts">
import { computed } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import type { ProfitTransferEvidence } from '../../../../../shared/erp-api'

const props = defineProps<{ evidence: ProfitTransferEvidence; canOpenJournal?: boolean }>()
const emit = defineEmits<{ openJournal: [id: number] }>()
const balances = [{ key: 'account', title: '损益科目' }, { key: 'balance', title: '待结余额（借正贷负，元）' },
  { key: 'debit', title: '结转借方（元）' }, { key: 'credit', title: '结转贷方（元）' }]
const sources = [{ key: 'journal_id', title: '来源凭证' }, { key: 'journal_date', title: '日期' },
  { key: 'reference', title: '依据编号' }, { key: 'account_id', title: '科目编号' },
  { key: 'line_id', title: '分录号' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const opening = [{ key: 'opening_balance_id', title: '正式期初来源' }, { key: 'account_id', title: '科目编号' },
  { key: 'line_id', title: '分录号' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const excluded = [{ key: 'code', title: '科目编码' }, { key: 'name', title: '未纳管成本科目' }, { key: 'balance', title: '余额（借正贷负，元）' }]
const targetLine = computed(() => props.evidence.lines.find(item => item.account_id === props.evidence.target_account_id))
</script>

<template>
  <div class="stack profit-transfer-evidence">
    <p>{{ evidence.start_date }} 至 {{ evidence.end_date }} · 人民币 · UTC · 科目配置版本 {{ evidence.policy_version }}</p>
    <p>待结转净额：{{ evidence.net_profit }} 元（盈利为正，亏损为负）。这是累计待结余额，包含正式期初及历史已过账凭证，不能作为本期利润表。</p>
    <WorkspaceTable title="损益科目与清零分录" :columns="balances" :snapshot-id="evidence.snapshot_id" snapshot-path="rows" :data="evidence.rows" :min-table-width="720">
      <template #cell-account="{ row }">{{ row.code }} · {{ row.name }}</template>
      <template #empty>纳管损益科目余额均为零。</template>
    </WorkspaceTable>
    <p v-if="evidence.target_account">转入 {{ evidence.target_account.code }} · {{ evidence.target_account.name }}：借方 {{ targetLine?.debit ?? '0.00' }} 元 / 贷方 {{ targetLine?.credit ?? '0.00' }} 元。净额为零时不生成本年利润分录。</p>
    <NCollapse>
      <AppCollapseItem name="source" :title="`已过账来源（${(evidence.sources.length || evidence.snapshot_id)} 条分录）与正式期初`">
        <div class="stack">
          <WorkspaceTable title="损益凭证来源" :columns="sources" :snapshot-id="evidence.snapshot_id" snapshot-path="sources" :data="evidence.sources" :min-table-width="900">
            <template #cell-journal_id="{ row }"><AppButton v-if="canOpenJournal" variant="text" @click="emit('openJournal', row.journal_id)">记-{{ row.journal_id }}</AppButton><span v-else>记-{{ row.journal_id }}</span></template>
            <template #empty>没有损益已过账来源。</template>
          </WorkspaceTable>
          <WorkspaceTable title="正式期初来源" :columns="opening" :snapshot-id="evidence.snapshot_id" snapshot-path="opening_sources" :data="evidence.opening_sources" :min-table-width="640">
            <template #cell-opening_balance_id="{ row }">期初-{{ row.opening_balance_id }}</template>
            <template #empty>没有纳入本次结转的正式期初损益余额。</template>
          </WorkspaceTable>
        </div>
      </AppCollapseItem>
      <AppCollapseItem v-if="(evidence.excluded_cost_accounts.length || evidence.snapshot_id)" name="excluded" :title="`未纳管成本余额（${(evidence.excluded_cost_accounts.length || evidence.snapshot_id)} 个科目）`">
        <p class="muted">这些科目保留余额，不参与本次结转。生产成本及在制品应按公司的成本核算规则处理。</p>
        <WorkspaceTable title="保留的成本余额" :columns="excluded" :snapshot-id="evidence.snapshot_id" snapshot-path="excluded_cost_accounts" :data="evidence.excluded_cost_accounts" :min-table-width="640" />
      </AppCollapseItem>
    </NCollapse>
  </div>
</template>

<style scoped>
/* 外层面板和凭证弹窗共用证据；展开后由外层承接纵向滚动。 */
.profit-transfer-evidence { min-width: 0; grid-template-columns: minmax(0, 1fr); }
.profit-transfer-evidence :deep(.vxe-table--viewport-wrapper) { overflow: clip; }
</style>
