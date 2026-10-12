import { watch } from 'vue'
import type { AppState } from '../state'
import type { ControlBalanceTransfer, ControlTransferInput, ControlFundsQuery, ControlFundsOptions } from '../../../../shared/control-balance-api'
import type { Journal } from '../../../../shared/erp-api'
import { controlTransferBody } from '../../../../shared/control-balance-validation.ts'
import { displayError } from '../../utils/formatters.ts'

export function createControlBalanceActions(state: AppState,
  perform: (run: () => Promise<unknown>, message: string) => Promise<void>, refreshHistory: () => Promise<void>) {
  let owner = 0, readTicket = 0, detailTicket = 0, reportTicket = 0, journalTicket = 0
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  const connected = () => !!window.nexora && !state.connectionLost.value
  function clear(): void {
    readTicket++; detailTicket++; reportTicket++; journalTicket++
    state.controlBalanceTransfers.value = []; state.controlBalanceOptions.value = null
    state.controlBalanceDetail.value = null; state.controlBalanceChanges.value = []
    state.controlBalanceJournal.value = null
    state.controlBalanceReport.value = null; state.controlBalanceError.value = ''; state.controlBalanceLoading.value = false
    state.controlBalanceReportLoading.value = false
  }
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`,
    () => { owner++; clear() }, { flush: 'sync' })
  watch(state.connectionLost, () => { owner++; clear() }, { flush: 'sync' })
  const valid = (session: number) => session === owner && connected() && can('control_transfer.view')
  function guard(session: number, permissions: string[]): void {
    if (!valid(session) || permissions.some(code => !can(code))) throw Error('往来余额转账的会话、连接或权限已变化，请重新读取。')
  }
  async function loadControlBalances(): Promise<boolean> {
    if (!connected() || !can('control_transfer.view')) return false
    const session = owner, ticket = ++readTicket
    state.controlBalanceLoading.value = true; state.controlBalanceError.value = ''
    state.controlBalanceTransfers.value = []; state.controlBalanceOptions.value = null
    try {
      const [records, options] = await Promise.allSettled([window.nexora!.callApi('controlBalanceTransfers', undefined),
        window.nexora!.callApi('controlBalanceOptions', undefined)])
      if (!valid(session) || ticket !== readTicket) return false
      if (records.status === 'fulfilled') state.controlBalanceTransfers.value = records.value
      if (options.status === 'fulfilled') state.controlBalanceOptions.value = options.value
      state.controlBalanceError.value = [records, options].filter(result => result.status === 'rejected')
        .map(result => displayError((result as PromiseRejectedResult).reason)).join('；')
      return records.status === 'fulfilled'
    } finally { if (session === owner && ticket === readTicket) state.controlBalanceLoading.value = false }
  }
  async function loadControlBalanceDetail(id: number): Promise<boolean> {
    if (!connected() || !can('control_transfer.view')) return false
    const session = owner, ticket = ++detailTicket
    state.controlBalanceDetail.value = null; state.controlBalanceChanges.value = []; state.controlBalanceError.value = ''
    try {
      const [record, changes] = await Promise.all([window.nexora!.callApi('controlBalanceDetail', { id }),
        window.nexora!.callApi('controlBalanceChanges', { id })])
      if (!valid(session) || ticket !== detailTicket) return false
      state.controlBalanceDetail.value = record; state.controlBalanceChanges.value = changes; return true
    } catch (error) { if (valid(session) && ticket === detailTicket) state.controlBalanceError.value = displayError(error); return false }
  }
  function closeControlBalanceDetail(): void {
    detailTicket++; state.controlBalanceDetail.value = null; state.controlBalanceChanges.value = []
  }
  function closeControlBalanceJournal(): void { journalTicket++; state.controlBalanceJournal.value = null }
  async function loadControlBalanceJournal(id: number): Promise<boolean> {
    if (!valid(owner) || !can('journal.view')) return false
    const session = owner, ticket = ++journalTicket
    state.controlBalanceJournal.value = null; state.controlBalanceError.value = ''
    try {
      const journal = await window.nexora!.callApi('journalDetail', { id })
      if (!valid(session) || ticket !== journalTicket || !can('journal.view')) return false
      state.controlBalanceJournal.value = journal; return true
    } catch (error) { if (valid(session) && ticket === journalTicket) state.controlBalanceError.value = displayError(error); return false }
  }
  async function queryControlBalances(to_date: string): Promise<boolean> {
    if (!connected() || !can('control_transfer.view')) return false
    const session = owner, ticket = ++reportTicket
    state.controlBalanceReport.value = null; state.controlBalanceError.value = ''
    state.controlBalanceReportLoading.value = true
    try {
      const report = await window.nexora!.callApi('queryControlBalances', { to_date })
      if (!valid(session) || ticket !== reportTicket) return false
      state.controlBalanceReport.value = report; return true
    } catch (error) { if (valid(session) && ticket === reportTicket) state.controlBalanceError.value = displayError(error); return false }
    finally { if (session === owner && ticket === reportTicket) state.controlBalanceReportLoading.value = false }
  }
  async function loadControlFundsOptions(input: ControlFundsQuery): Promise<ControlFundsOptions> {
    if (!connected() || !can('finance.record')) throw Error('没有读取资金组合的权限或服务已断开。')
    const session = owner, result = await window.nexora!.callApi('controlBalanceFundsOptions', { ...input })
    if (session !== owner || !connected() || !can('finance.record')) throw Error('资金组合的会话已变化，请重新选择原单。')
    return result
  }
  const transferPermission = (row: ControlBalanceTransfer) => row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.post'
  const current = (row: ControlBalanceTransfer) => state.controlBalanceTransfers.value.find(item => item.id === row.id
    && item.version === row.version && item.approval?.version === row.approval?.version)
  async function write(permissions: string[], run: () => Promise<unknown>, message: string): Promise<boolean> {
    if (!valid(owner) || state.busy.value || permissions.some(code => !can(code))) return false
    const session = owner; let saved = false
    await perform(async () => { guard(session, permissions); await run(); saved = valid(session) }, message)
    if (!saved || !valid(session)) return false
    await loadControlBalances()
    if (!valid(session)) return false
    await refreshHistory()
    return valid(session)
  }
  return { loadControlBalances, loadControlBalanceDetail, closeControlBalanceDetail, queryControlBalances, loadControlFundsOptions,
    loadControlBalanceJournal, closeControlBalanceJournal,
    cancelControlBalanceJournal: (row: ControlBalanceTransfer, journal: Journal, reason: string) => {
      if (!current(row) || row.status !== 'draft' || row.journal_id !== journal.id
        || !['draft','rejected','submitted','approved'].includes(journal.status)
        || ['submitted','approved'].includes(journal.approval?.status ?? '')) return Promise.resolve(false)
      return write([row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.create', 'journal.view', 'journal.cancel'], async () => {
        if (!current(row) || state.controlBalanceJournal.value?.id !== journal.id
          || state.controlBalanceJournal.value.version !== journal.version || state.controlBalanceJournal.value.approval?.version !== journal.approval?.version) throw Error('关联凭证或审批已变化，请重新核对。')
        await window.nexora!.callApi('changeJournalStatus', { id: journal.id, version: journal.version, action: 'cancel', reason })
      }, '未过账的关联凭证已取消，可重新生成或取消转账草稿。')
    },
    postControlBalanceJournal: (row: ControlBalanceTransfer, journal: Journal, reason: string) => {
      if (!current(row) || row.status !== 'draft' || row.approval?.status !== 'approved' || row.journal_id !== journal.id
        || journal.status !== 'approved' || journal.approval?.status !== 'approved') return Promise.resolve(false)
      return write([transferPermission(row), 'journal.view', 'journal.post'], async () => {
        if (!current(row) || state.controlBalanceJournal.value?.id !== journal.id
          || state.controlBalanceJournal.value.version !== journal.version || state.controlBalanceJournal.value.approval?.version !== journal.approval?.version) throw Error('转账或凭证审批已变化，请重新核对。')
        await window.nexora!.callApi('changeJournalStatus', { id: journal.id, version: journal.version, action: 'post', reason })
      }, '凭证已过账，余额转账在同一事务中生效。')
    },
    createControlBalanceTransfer: (input: ControlTransferInput) => {
      let plain: ControlTransferInput
      try { plain = controlTransferBody(input) }
      catch (error) { state.error.value = displayError(error); return Promise.resolve(false) }
      return write(['control_transfer.create'], () => window.nexora!.callApi('createControlBalanceTransfer', plain), '转账草稿已保存，批准及生成凭证均不改变余额。')
    },
    generateControlBalanceJournal: (row: ControlBalanceTransfer, reference: string, reason: string) => {
      if (!current(row) || row.status !== 'draft' || row.approval?.status !== 'approved'
        || row.journal_id && row.journal_status !== 'cancelled') return Promise.resolve(false)
      return write([transferPermission(row), 'journal.create'], async () => {
        if (!current(row)) throw Error('转账或审批已变化，请重新核对。')
        await window.nexora!.callApi('generateControlBalanceJournal', { id: row.id, version: row.version, reference, reason })
      }, '固定组合凭证已生成，须独立批准并过账后才生效。')
    },
    reverseControlBalanceTransfer: (row: ControlBalanceTransfer, business_date: string, reference: string, reason: string) => {
      if (!current(row) || row.status !== 'executed' || row.reverses_id || row.reversal_id) return Promise.resolve(false)
      return write(['control_transfer.reverse'], async () => {
        if (!current(row)) throw Error('原转账已变化，请重新核对。')
        await window.nexora!.callApi('reverseControlBalanceTransfer', { id: row.id, version: row.version, business_date, reference, reason })
      }, '等额反向转账草稿已建立，原记录保留；重新批准和过账后才恢复归属。')
    },
    cancelControlBalanceTransfer: (row: ControlBalanceTransfer, reason: string) => {
      if (!current(row) || row.status !== 'draft' || ['submitted','approved'].includes(row.approval?.status ?? '')
        || row.journal_id && row.journal_status !== 'cancelled') return Promise.resolve(false)
      return write([row.reverses_id ? 'control_transfer.reverse' : 'control_transfer.create'], async () => {
        if (!current(row)) throw Error('转账已变化，请重新核对。')
        await window.nexora!.callApi('cancelControlBalanceTransfer', { id: row.id, version: row.version, reason })
      }, '未生效转账已取消。')
    }
  }
}
