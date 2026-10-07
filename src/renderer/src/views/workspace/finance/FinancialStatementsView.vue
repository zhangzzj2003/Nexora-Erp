<script setup lang="ts">
// 凭证与来源保留内部 ID，界面优先显示服务端保存的业务单号。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker, NModal, NCollapse } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { datePickerString, dateOutsideRange, vDateField } from '../../../utils/date-field'
import { localTime } from '../../../utils/formatters'
import { statementPolicyDescription, statementGroups } from './statement-display'
import { journalStatusLabels } from './journal-display'
import { auxiliaryText } from './auxiliary-display'
import StatementPolicyEditor from './StatementPolicyEditor.vue'
import StatementReportView from './StatementReportView.vue'
import JournalHistory from './JournalHistory.vue'
import BusinessSourceEvidence from './BusinessSourceEvidence.vue'
import ProfitTransferEvidence from './ProfitTransferEvidence.vue'
import './financial-statements.css'

const store = usePiniaAppStore()
const { statementOptions: options, statementPolicyChanges: changes, statementQuery: query,
  statementReport: report, statementArchives: archives, statementArchive: archive,
  statementLoading: loading, statementArchiveLoading: archiveLoading, statementError: error,
  busy, connectionLost, user, ledgerReportJournal: journal, ledgerReportJournalLoading: journalLoading,
  ledgerReportJournalError: journalError } = storeToRefs(store)
const { can, loadStatementOptions, queryStatement, archiveStatement, openStatementArchive,
  closeStatementArchive, exportStatement, openLedgerReportJournal, closeLedgerReportJournal, loadJournalChanges } = store
const configure = ref(false)
const reason = ref('')
const periodId = ref(0)
const archiveVisible = ref(false)
let returnToArchive = false
const queryValid = computed(() => !loading.value && !connectionLost.value && !!options.value?.policy.version
  && !!query.value.from_date && !!query.value.to_date && query.value.from_date <= query.value.to_date)
const periods = computed(() => [{ value: 0, label: '自定日期范围' }, ...(options.value?.periods.map(item => ({
  value: item.id, label: `${item.code} · ${item.start_date} 至 ${item.end_date} · ${item.status === 'closed' ? '已结账' : '开放'}` })) ?? [])])
const historyColumns = [{ key: 'created_at', title: '时间', width: '180' }, { key: 'changed_by_name', title: '操作者', width: '120' },
  { key: 'before', title: '修改前', width: '260' }, { key: 'after', title: '修改后', width: '260' }, { key: 'reason', title: '依据', width: '230' }]
const archiveColumns = [{ key: 'range', title: '报表期间', width: '250' }, { key: 'policy_version', title: '配置版本', width: '110' },
  { key: 'created_at', title: '归档时间', width: '180' }, { key: 'created_by_name', title: '操作者', width: '130' },
  { key: 'reason', title: '依据', width: '240' }, { key: 'actions', title: '操作', width: '130' }]
const archiveRows = computed(() => archives.value.map(item => ({ ...item, range: `${item.from_date} 至 ${item.to_date}` })))
const journalColumns = [{ key: 'position', title: '序号' }, { key: 'account_name', title: '科目快照' },
  { key: 'summary', title: '摘要' }, { key: 'auxiliary', title: '辅助快照', width: '290' }, { key: 'debit', title: '借方（元）' }, { key: 'credit', title: '贷方（元）' }]
const modalStyle = { width: 'min(1180px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const }
onMounted(() => { void loadStatementOptions() })
// 写入成功后选项重新读取会卸载编辑器，父层负责关闭，避免旧组件的迟到事件失效。
watch(options, () => { if (!options.value) configure.value = false })
watch(report, () => { reason.value = ''; closeLedgerReportJournal() })
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => {
  configure.value = false; reason.value = ''; archiveVisible.value = false; returnToArchive = false; closeLedgerReportJournal()
}, { flush: 'sync' })
function selectPeriod(): void {
  const item = options.value?.periods.find(item => item.id === periodId.value)
  if (item) query.value = { from_date: item.start_date, to_date: item.end_date }
}
async function archiveCurrent(): Promise<void> {
  const item = report.value
  if (!item?.can_archive || busy.value || loading.value || connectionLost.value || !reason.value.trim()) return
  if (await archiveStatement({ ...item.filters, policy_version: item.policy_version, fingerprint: item.fingerprint, reason: reason.value })) reason.value = ''
}
async function inspectArchive(id: number): Promise<void> {
  archiveVisible.value = true; returnToArchive = false
  await openStatementArchive(id)
}
function closeArchive(): void { archiveVisible.value = false; returnToArchive = false; closeStatementArchive() }
async function inspectJournal(id: number): Promise<void> {
  if (!can('journal.view')) return
  if (archiveVisible.value) { returnToArchive = true; archiveVisible.value = false }
  await openLedgerReportJournal(id)
}
function closeJournal(): void {
  closeLedgerReportJournal()
  if (returnToArchive && archive.value) archiveVisible.value = true
  returnToArchive = false
}
</script>

<template>
  <section class="stack financial-statements-page">
    <form class="statement-query" @submit.prevent="queryStatement">
      <section class="card statement-query-panel" aria-label="财务报表查询">
        <div class="workspace-table-toolbar">
          <div class="workspace-table-filters">
            <label>会计期间<WorkspaceSelect v-model="periodId" :options="periods" :disabled="loading || connectionLost || !options" @change="selectPeriod" /></label>
            <label>开始日期<NDatePicker to="body" :formatted-value="query.from_date || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true }" :disabled="loading || connectionLost" @update:formatted-value="value => { periodId = 0; query.from_date = datePickerString(value) }" /></label>
            <label>结束日期<NDatePicker to="body" :formatted-value="query.to_date || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" v-date-field="{ required: true, min: query.from_date || undefined }" :is-date-disabled="(timestamp: number) => dateOutsideRange(timestamp, query.from_date || undefined, undefined)" :disabled="loading || connectionLost" @update:formatted-value="value => { periodId = 0; query.to_date = datePickerString(value) }" /></label>
          </div>
          <div class="workspace-table-toolbar-actions">
            <AppButton type="submit" variant="primary" :disabled="!queryValid">{{ loading ? '正在读取…' : '查询报表' }}</AppButton>
            <AppButton type="button" variant="secondary" :disabled="loading || busy || connectionLost || configure" @click="loadStatementOptions">重新读取</AppButton>
            <AppButton v-if="can('financial_statement.configure')" type="button" variant="secondary" :disabled="!options || loading || busy || connectionLost" @click="configure = !configure">{{ configure ? '收起配置' : '配置报表项目' }}</AppButton>
            <AppButton type="button" variant="secondary" :disabled="!report || loading || connectionLost" @click="report && exportStatement(report)">导出 CSV</AppButton>
          </div>
        </div>
        <p>资产负债与利润按公司项目编制，金额可追溯到同快照科目及分录；不预置法定格式。</p>
        <p v-if="options">{{ statementPolicyDescription(options.policy) }}</p>
        <p v-if="error" role="alert">读取失败：{{ error }}，请重新读取或重新查询。</p>
        <p v-else-if="loading" role="status">正在读取配置、报表或历史…</p>
        <p v-else-if="!options" role="status">配置尚未读取，请重新读取。</p>
        <p v-else-if="!options.policy.version" role="status">尚未配置公司报表项目。有配置权限的账号需先建立项目并分配科目。</p>
        <p v-else-if="!report" role="status">选择日期或期间后查询报表。开放期间可查询，归档仅接受完整关闭期间。</p>
      </section>
    </form>
    <StatementPolicyEditor v-if="configure && options && can('financial_statement.configure')" :key="options.policy.version" :options="options" @close="configure = false" />
    <StatementReportView v-if="report" :key="report.fingerprint" :report="report" :can-open-journal="can('journal.view')" :offline="connectionLost" @open-journal="inspectJournal" />
    <form v-if="report && can('financial_statement.archive')" class="statement-archive-form" @submit.prevent="archiveCurrent">
      <label>归档依据<AppInput v-model="reason" required maxlength="500" placeholder="说明核对结果与归档依据" :disabled="busy || loading || connectionLost || !report.can_archive" /></label>
      <AppButton type="submit" variant="primary" :disabled="busy || loading || connectionLost || !report.can_archive || !reason.trim()">归档当前报表</AppButton>
      <p>归档会重新核对服务器来源，保留金额、项目、科目和分录快照；之后的更正或配置修改不会改写旧归档。</p>
    </form>
    <WorkspaceTable title="报表归档" :data="archiveRows" :columns="archiveColumns" :min-table-width="1040">
      <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
      <template #cell-actions="{ row }"><AppButton type="button" variant="text" :disabled="connectionLost || archiveLoading" @click="inspectArchive(row.id)">查看快照</AppButton></template>
      <template #empty>暂无归档。请先完成项目配置和期间核对，关闭期间后归档。</template>
    </WorkspaceTable>
    <NCollapse><AppCollapseItem name="statement-history" title="报表配置变更记录"><WorkspaceTable title="配置变更记录" :data="changes" :columns="historyColumns" :min-table-width="1050">
      <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
      <template v-for="field in (['before', 'after'] as const)" #[`cell-${field}`]="{ row }"><NCollapse><AppCollapseItem :name="`policy-${row.id}-${field}`" :title="statementPolicyDescription(row[field])"><template v-if="row[field]"><ul><li v-for="line in row[field]!.lines" :key="line.code">{{ line.code }} · {{ line.name }} · {{ statementGroups[line.group] }}</li></ul><ul><li v-for="item in row[field]!.allocations" :key="item.account_id">科目 #{{ item.account_id }} → {{ item.line_code }}</li></ul><p>手工结转：{{ row[field]!.manual_transfer_ids.map(id => `记-${id}`).join('、') || '无' }}</p></template></AppCollapseItem></NCollapse></template>
    </WorkspaceTable></AppCollapseItem></NCollapse>
    <NModal :show="archiveVisible" preset="card" :title="archive ? `财务报表归档 #${archive.id}` : '读取报表归档'" :style="modalStyle" @update:show="value => { if (!value) closeArchive() }">
      <p v-if="archiveLoading" role="status">正在读取归档快照…</p><p v-if="error" role="alert">{{ error }}</p>
      <div v-if="archive" class="stack"><p>归档于 {{ localTime(archive.created_at) }} · 操作者 {{ archives.find(item => item.id === archive!.id)?.created_by_name || `账号 #${archive.created_by}` }} · 依据 {{ archive.reason }}</p><AppButton type="button" variant="secondary" :disabled="connectionLost" @click="exportStatement(archive.snapshot)">导出归档 CSV</AppButton><StatementReportView :key="archive.id" :report="archive.snapshot" archived :can-open-journal="can('journal.view')" :offline="connectionLost" @open-journal="inspectJournal" /></div>
    </NModal>
    <NModal :show="!!journal || journalLoading || !!journalError" preset="card" :title="journal ? `${documentLabel(journal)} · ${journalStatusLabels[journal.status]}` : '当前凭证详情'" :style="modalStyle" @update:show="value => { if (!value) closeJournal() }">
      <p v-if="journalLoading" role="status">正在读取凭证…</p><p v-if="journalError" role="alert">{{ journalError }}</p>
      <div v-if="journal" class="stack"><p>{{ journal.journal_date }} · 期间 {{ journal.period_code }} · 依据 {{ journal.reference }} · 建单人 {{ journal.created_by_name }} · 当前版本 {{ journal.version }}</p><p v-if="journal.note">备注：{{ journal.note }}</p>
        <p v-if="journal.reversal_of_id">冲销原凭证：<AppButton type="button" variant="text" :disabled="connectionLost" @click="inspectJournal(journal.reversal_of_id)">{{ relatedDocumentLabel(journal, 'reversal_of') }}</AppButton></p>
        <WorkspaceTable title="当前凭证分录" :data="journal.lines" :columns="journalColumns" :min-table-width="1090"><template #cell-account_name="{ row }">{{ row.account_code }} · {{ row.account_name }}</template><template #cell-auxiliary="{ row }">{{ auxiliaryText(row.auxiliary) }}</template></WorkspaceTable>
        <NCollapse><AppCollapseItem v-if="journal.business_source" name="business" title="生成时的业务来源"><BusinessSourceEvidence :source="journal.business_source.evidence" :mapping="journal.business_source.mapping" /></AppCollapseItem><AppCollapseItem v-if="journal.profit_transfer" name="transfer" title="生成时的损益结转来源"><ProfitTransferEvidence :evidence="journal.profit_transfer.evidence" :can-open-journal="can('journal.view')" @open-journal="inspectJournal" /></AppCollapseItem></NCollapse>
        <JournalHistory :key="`${journal.id}:${journal.version}`" :load="() => loadJournalChanges(journal!.id)" />
      </div>
    </NModal>
  </section>
</template>
