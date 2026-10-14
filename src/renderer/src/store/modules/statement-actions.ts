import { watch } from 'vue'
import type { StatementArchiveInput, StatementPolicy, StatementReport } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createStatementActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let ticket = 0; let detailTicket = 0; let owner = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const connected = (): boolean => !!window.nexora && !state.connectionLost.value
  function closeStatementArchive(): void {
    detailTicket++; state.statementArchive.value = null; state.statementArchiveLoading.value = false
  }
  function invalidate(): void {
    ticket++; state.statementReport.value = null; state.statementLoading.value = false; state.statementError.value = ''
    closeStatementArchive()
  }
  watch(state.statementQuery, invalidate, { deep: true, flush: 'sync' })
  // 稳定身份字段避免常规账号刷新关闭详情，切服和断线仍立即失效。
  // 角色与权限按集合比较，副本排序不会修改用户快照，例行返回顺序变化也不取消读取。
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.slice().sort().join('|')}:${state.user.value?.permissions.slice().sort().join('|')}:${state.connectionLost.value}`, () => {
    owner++; invalidate(); state.statementOptions.value = null
    state.statementPolicyChanges.value = []; state.statementArchives.value = []
  }, { flush: 'sync' })
  async function loadStatementOptions(): Promise<boolean> {
    if (!can('financial_statement.view') || !connected()) return false
    invalidate()
    state.statementOptions.value = null; state.statementPolicyChanges.value = []; state.statementArchives.value = []
    const current = ++ticket; state.statementLoading.value = true
    try {
      const [options, history, archives] = await Promise.all([
        window.nexora!.callApi('statementOptions', undefined),
        window.nexora!.callApi('statementPolicyChanges', undefined),
        window.nexora!.callApi('statementArchives', undefined)
      ])
      if (current !== ticket || !connected() || !can('financial_statement.view')) return false
      state.statementOptions.value = options; state.statementPolicyChanges.value = history; state.statementArchives.value = archives
      return true
    } catch (error) {
      if (current === ticket) state.statementError.value = displayError(error)
      return false
    } finally { if (current === ticket) state.statementLoading.value = false }
  }
  async function queryStatement(): Promise<boolean> {
    if (!can('financial_statement.view') || !connected()) return false
    invalidate()
    const current = ++ticket; state.statementLoading.value = true
    const filters = { ...state.statementQuery.value }
    try {
      const result = await window.nexora!.callApi('queryStatement', filters)
      if (current !== ticket || !connected() || !can('financial_statement.view')) return false
      state.statementReport.value = result
      return true
    } catch (error) {
      if (current === ticket) state.statementError.value = displayError(error)
      return false
    } finally { if (current === ticket) state.statementLoading.value = false }
  }
  async function openStatementArchive(id: number): Promise<boolean> {
    if (!can('financial_statement.view') || !connected()) return false
    // 归档不可变，同一归档重读时保留旧快照，换归档则先撤下旧内容。
    if (state.statementArchive.value?.id !== id) closeStatementArchive()
    const current = ++detailTicket; state.statementArchiveLoading.value = true; state.statementError.value = ''
    try {
      const result = await window.nexora!.callApi('statementArchiveDetail', { id })
      if (current !== detailTicket || !connected() || !can('financial_statement.view')) return false
      if (result.id !== id) throw Error('报表归档与当前选择不一致，请重新读取。')
      state.statementArchive.value = result
      return true
    } catch (error) {
      if (current === detailTicket) state.statementError.value = displayError(error)
      return false
    } finally { if (current === detailTicket) state.statementArchiveLoading.value = false }
  }
  async function write(permission: string, action: () => Promise<unknown>, success: string): Promise<boolean> {
    if (!can(permission) || !connected() || state.busy.value) return false
    const current = owner; let saved = false
    await perform(async () => { await action(); saved = current === owner && can(permission) }, success)
    if (!saved || current !== owner || !can(permission)) return false
    await loadStatementOptions()
    return current === owner && can(permission)
  }
  async function exportStatement(report: StatementReport): Promise<void> {
    if (!can('financial_statement.view') || !connected()) return
    const current = owner
    // 只导出当前查询或已打开归档，页面不能将别的旧快照偷偷交给导出动作。
    if (report !== state.statementReport.value && report !== state.statementArchive.value?.snapshot) return
    try {
      const saved = await window.nexora!.saveReportCsv(`statements-${report.filters.from_date}-${report.filters.to_date}.csv`, report.csv)
      if (saved && current === owner && can('financial_statement.view')) state.notice.value = '财务报表 CSV 已保存。'
    } catch (error) { if (current === owner) state.statementError.value = displayError(error) }
  }
  return {
    loadStatementOptions, queryStatement, openStatementArchive, closeStatementArchive, exportStatement,
    saveStatementPolicy: (input: StatementPolicy & { reason: string }) => {
      const fields = { ...input, lines: input.lines.map(item => ({ ...item })),
        allocations: input.allocations.map(item => ({ ...item })), manual_transfer_ids: [...input.manual_transfer_ids] }
      return write('financial_statement.configure', () => window.nexora!.callApi('saveStatementPolicy', fields), '财务报表配置已保存，旧归档保持原快照。')
    },
    archiveStatement: (input: StatementArchiveInput) => write('financial_statement.archive',
      () => window.nexora!.callApi('archiveStatement', { ...input }), '财务报表已归档，金额及来源快照保持不变。')
  }
}
