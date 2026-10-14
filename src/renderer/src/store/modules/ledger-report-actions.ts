import { watch } from 'vue'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

// 查询独立于业务写操作；条件或会话改变后，过期响应不得覆盖新结果。
export function createLedgerReportActions(state: AppState) {
  let queryTicket = 0; let optionsTicket = 0; let detailTicket = 0
  const allowed = (): boolean => state.user.value?.permissions.includes('journal.view') ?? false
  const connected = (): boolean => !!window.nexora && !state.connectionLost.value
  function closeLedgerReportJournal(): void {
    detailTicket++
    state.ledgerReportJournal.value = null
    state.ledgerReportJournalLoading.value = false
    state.ledgerReportJournalError.value = ''
  }
  function invalidate(): void {
    queryTicket++
    state.ledgerReportResult.value = null
    state.ledgerReportLoading.value = false
    state.ledgerReportError.value = ''
    closeLedgerReportJournal()
  }
  watch(state.ledgerReportQuery, invalidate, { deep: true, flush: 'sync' })
  // 不监听 user 对象身份，只有账号、权限、实例或连接实际变化才清理详情。
  // 角色与权限按集合比较，副本排序不会修改用户快照，例行返回顺序变化也不取消读取。
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.slice().sort().join('|')}:${state.user.value?.permissions.slice().sort().join('|')}:${state.connectionLost.value}`, () => {
    invalidate(); optionsTicket++
    state.ledgerReportAccounts.value = []
  }, { flush: 'sync' })
  async function loadLedgerReportOptions(): Promise<void> {
    if (!allowed() || !connected()) return
    const ticket = ++optionsTicket
    try {
      const accounts = await window.nexora!.callApi('ledgerReportOptions', undefined)
      if (ticket === optionsTicket && allowed()) state.ledgerReportAccounts.value = accounts
    } catch (cause) {
      if (ticket === optionsTicket) state.ledgerReportError.value = `科目选项读取失败：${displayError(cause)}`
    }
  }
  async function queryLedgerReport(): Promise<void> {
    if (!allowed() || !connected()) return
    invalidate()
    const ticket = ++queryTicket
    const { kind, from_date, to_date, account_id } = state.ledgerReportQuery.value
    state.ledgerReportLoading.value = true
    try {
      const result = await window.nexora!.callApi('queryLedgerReport', { kind, from_date, to_date, account_id })
      if (ticket === queryTicket && allowed()) state.ledgerReportResult.value = result
    } catch (cause) {
      if (ticket === queryTicket) state.ledgerReportError.value = displayError(cause)
    } finally {
      if (ticket === queryTicket) state.ledgerReportLoading.value = false
    }
  }
  async function openLedgerReportJournal(id: number): Promise<boolean> {
    if (!allowed() || !connected()) return false
    // 同凭证刷新保留正文，错误状态继续阻止界面依赖旧快照执行操作。
    if (state.ledgerReportJournal.value?.id !== id) closeLedgerReportJournal()
    state.ledgerReportJournalError.value = ''
    const ticket = ++detailTicket
    state.ledgerReportJournalLoading.value = true
    try {
      const record = await window.nexora!.callApi('journalDetail', { id })
      if (ticket !== detailTicket || !allowed() || !connected()) return false
      if (record.id !== id) throw Error('凭证详情与当前选择不一致，请重新读取。')
      state.ledgerReportJournal.value = record
      return true
    } catch (cause) {
      if (ticket === detailTicket) state.ledgerReportJournalError.value = displayError(cause)
      return false
    } finally {
      if (ticket === detailTicket) state.ledgerReportJournalLoading.value = false
    }
  }
  async function exportLedgerReport(): Promise<void> {
    const result = state.ledgerReportResult.value
    if (!result || !allowed() || !connected()) return
    try {
      const saved = await window.nexora!.saveReportCsv(
        `${result.kind}-${result.filters.from_date}-${result.filters.to_date}.csv`, result.csv)
      if (saved && allowed()) state.notice.value = '总账报表 CSV 已保存。'
    } catch (cause) { state.ledgerReportError.value = displayError(cause) }
  }
  return { loadLedgerReportOptions, queryLedgerReport, openLedgerReportJournal, closeLedgerReportJournal, exportLedgerReport }
}
