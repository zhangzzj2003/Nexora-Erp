<script setup lang="ts">
// 凭证与来源保留内部 ID，界面优先显示服务端保存的业务单号。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, nextTick, ref } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type { StatementReport } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import AppButton from '../../../components/app/AppButton.vue'
import { statementContributions, statementGroups } from './statement-display'
import { journalStatusLabels } from './journal-display'
import { auxiliaryText } from './auxiliary-display'

const props = defineProps<{ report: StatementReport; archived?: boolean; canOpenJournal: boolean; offline: boolean }>()
const emit = defineEmits<{ openJournal: [id: number] }>()
const selected = ref<{ code: string; name: string; ids: number[] } | null>(null)
const evidence = ref<HTMLElement | null>(null)
const balanceColumns = [{ key: 'group', title: '分组', width: '170' }, { key: 'name', title: '项目', width: '260' },
  { key: 'opening', title: '期初余额（元）', width: '170' }, { key: 'amount', title: '期末余额（元）', width: '170' }, { key: 'sources', title: '核对', width: '120' }]
const incomeColumns = balanceColumns.filter(item => item.key !== 'opening').map(item => item.key === 'amount' ? { ...item, title: '本期金额（元）' } : item)
const contributionColumns = [{ key: 'code', title: '科目编码', width: '110' }, { key: 'name', title: '科目名称', width: '220' },
  { key: 'opening', title: '期初（元）', width: '150' }, { key: 'closing', title: '期末（元）', width: '150' }, { key: 'movement', title: '本期发生额（元）', width: '170' }]
const sourceColumns = [{ key: 'journal_date', title: '日期', width: '120' }, { key: 'journal_id', title: '凭证', width: '100' },
  { key: 'reference', title: '依据', width: '190' }, { key: 'account', title: '科目', width: '200' }, { key: 'summary', title: '摘要', width: '190' },
  { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）', width: '150' }, { key: 'credit', title: '贷方（元）', width: '150' }, { key: 'scope', title: '利润表口径', width: '180' }]
const openingColumns = [{ key: 'account', title: '科目' }, { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const unmappedColumns = [{ key: 'code', title: '科目编码' }, { key: 'name', title: '科目名称' }, { key: 'opening', title: '期初（元）' }, { key: 'closing', title: '期末（元）' }, { key: 'movement', title: '本期发生额（元）' }]
const contributions = computed(() => selected.value ? statementContributions(props.report, selected.value.code) : [])
function accountLabel(id: number): string {
  const account = [...props.report.contributions, ...props.report.unmapped].find(item => item.account_id === id)
  return account ? `${account.code} · ${account.name}` : `科目 #${id}`
}
const sources = computed(() => props.report.sources.filter(item => selected.value?.ids.includes(item.account_id))
  .map(item => ({ ...item, account: accountLabel(item.account_id), scope: item.excluded_from_income ? '结转／冲销，排除' : item.journal_date < props.report.filters.from_date ? '以前期间发生额' : '本期发生额（按科目归类）' })))
const openings = computed(() => props.report.opening_sources.filter(item => selected.value?.ids.includes(item.account_id))
  .map(item => ({ ...item, account: accountLabel(item.account_id) })))
async function inspect(row: { code: string; name: string; account_ids: number[] }): Promise<void> {
  selected.value = { code: row.code, name: row.name, ids: row.account_ids }
  await nextTick(); evidence.value?.scrollIntoView({ block: 'nearest' })
}
</script>

<template>
  <div class="stack statement-report">
    <div class="statement-report-context">
      <p><strong>{{ archived ? '已归档快照' : report.can_archive ? '已核对，可归档' : '核对中' }}</strong> · {{ report.filters.from_date }} 至 {{ report.filters.to_date }} · 人民币 · 配置版本 {{ report.policy_version }} · 生成于 {{ new Date(report.generated_at).toLocaleString('zh-CN', { hour12: false }) }}</p>
      <p>{{ report.opening_balance_id ? `正式期初来源：${relatedDocumentLabel(report, 'opening_balance')}` : '尚无正式期初：期初仅来自历史已过账金额累计。' }}</p>
      <p v-if="archived">金额、配置与下列来源保留归档时的快照；凭证详情会另读当前记录。</p>
      <ul v-if="report.blockers.length" aria-label="归档阻止事项"><li v-for="item in report.blockers" :key="item">{{ item }}</li></ul>
      <NCollapse><AppCollapseItem name="statement-rules" title="报表口径"><ul><li v-for="item in report.warnings" :key="item">{{ item }}</li></ul></AppCollapseItem></NCollapse>
    </div>
    <WorkspaceTable title="资产负债表" :columns="balanceColumns" :data="report.balance_rows" :min-table-width="830">
      <template #cell-group="{ row }">{{ statementGroups[row.group] }}</template>
      <template #cell-name="{ row }">{{ row.name }}<span class="muted"> · {{ row.code }}</span></template>
      <template #cell-opening="{ row }"><span class="statement-money">{{ row.opening }}</span></template>
      <template #cell-amount="{ row }"><span class="statement-money">{{ row.amount }}</span></template>
      <template #cell-sources="{ row }"><AppButton type="button" variant="text" @click="inspect(row)" :aria-label="`核对${row.name}来源`">核对来源</AppButton></template>
      <template #footer><p class="statement-totals">资产 {{ report.totals.assets }} · 负债 {{ report.totals.liabilities }} · 权益（含未结转损益）{{ report.totals.equity }} · 期初差额 {{ report.totals.opening_difference }} · 期末差额 {{ report.totals.closing_difference }} 元</p></template>
    </WorkspaceTable>
    <WorkspaceTable title="利润表" :columns="incomeColumns" :data="report.income_rows" :min-table-width="720">
      <template #cell-group="{ row }">{{ statementGroups[row.group] }}</template>
      <template #cell-name="{ row }">{{ row.name }}<span class="muted"> · {{ row.code }}</span></template>
      <template #cell-amount="{ row }"><span class="statement-money">{{ row.amount }}</span></template>
      <template #cell-sources="{ row }"><AppButton type="button" variant="text" @click="inspect(row)" :aria-label="`核对${row.name}来源`">核对来源</AppButton></template>
      <template #footer><p class="statement-totals">收入 {{ report.totals.revenue }} − 费用及销售成本 {{ report.totals.expense }} = <strong>本期净利润 {{ report.totals.net_profit }} 元</strong></p></template>
    </WorkspaceTable>
    <section v-if="selected" ref="evidence" class="stack statement-evidence" aria-label="报表来源核对">
      <div class="statement-actions"><h3>{{ selected.name }} · 来源核对</h3><AppButton type="button" variant="secondary" @click="selected = null">收起来源</AppButton></div>
      <p>以下金额与报表来自同一快照。科目本期发生额按收入贷减借、其他借减贷列示，排除结转；资产负债取期末余额，利润取本期发生额。未结转损益按收入余额减费用余额汇总。</p>
      <WorkspaceTable title="科目贡献" :columns="contributionColumns" :data="contributions" :min-table-width="800" />
      <WorkspaceTable v-if="report.opening_balance_id" :title="`正式期初来源 · ${relatedDocumentLabel(report, 'opening_balance')}`" :columns="openingColumns" :data="openings" :min-table-width="890"><template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template></WorkspaceTable>
      <WorkspaceTable title="已过账分录来源" :columns="sourceColumns" :data="sources" :min-table-width="1670">
        <template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template>
        <template #cell-journal_id="{ row }"><AppButton v-if="canOpenJournal" type="button" variant="text" :disabled="offline" @click="emit('openJournal', row.journal_id)">{{ relatedDocumentLabel(row, 'journal') }}</AppButton><span v-else>{{ relatedDocumentLabel(row, 'journal') }}</span></template>
        <template #footer><p>{{ canOpenJournal ? '点击凭证编号查看当前分录、来源证据与操作记录。' : '当前账号仅查看报表来源快照；另有凭证查看权限才可打开当前凭证。' }} 本表包含截至期末的历史分录，借贷原值未改变；本期利润只取日期范围内的损益科目。</p></template>
      </WorkspaceTable>
    </section>
    <WorkspaceTable v-if="report.unmapped.length" title="未映射非零科目" :columns="unmappedColumns" :data="report.unmapped" :min-table-width="800" />
    <div v-if="report.pending.length || report.unclassified_transfers.length" class="statement-report-context">
      <p v-if="report.pending.length">待处理凭证：<span v-for="item in report.pending" :key="item.id"><AppButton v-if="canOpenJournal" type="button" variant="text" :disabled="offline" @click="emit('openJournal', item.id)">{{ documentLabel(item) }}</AppButton><span v-else>{{ documentLabel(item) }}</span>（{{ journalStatusLabels[item.status] }}，{{ item.date }}） </span></p>
      <p v-if="report.unclassified_transfers.length">待核对手工结转：<span v-for="id in report.unclassified_transfers" :key="id"><AppButton v-if="canOpenJournal" type="button" variant="text" :disabled="offline" @click="emit('openJournal', id)">记-{{ id }}</AppButton><span v-else>记-{{ id }}</span> </span>；请核对后在配置中明确结转范围。</p>
    </div>
  </div>
</template>
