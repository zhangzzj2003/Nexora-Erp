import { watch } from 'vue'
import type { OpeningBalanceAction, SubledgerOpening, SubledgerPaymentInput, SubledgerPayment } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createSubledgerActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let owner = 0; let readTicket = 0; let queryTicket = 0; let detailTicket = 0; let editTicket = 0; let loadingTicket = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const connected = (): boolean => !!window.nexora && !state.connectionLost.value
  const emptyForm = () => ({ id: null, version: 1, reference: '', opening_balance_id: 0, opening_version: 0,
    control_accounts: [], lines: [], note: '', reason: '' })
  function clearReport(): void { queryTicket++; state.subledgerReport.value = null; state.subledgerError.value = '' }
  function invalidateReads(): void {
    readTicket++; queryTicket++; detailTicket++; editTicket++; loadingTicket++
    state.subledgerLoading.value = false; state.subledgerReport.value = null
    state.subledgerChanges.value = []; state.subledgerCheck.value = null; state.subledgerError.value = ''
  }
  function clearSubledgerDetail(): void {
    detailTicket++; state.subledgerChanges.value = []; state.subledgerCheck.value = null
  }
  watch(state.subledgerQuery, clearReport, { deep: true, flush: 'sync' })
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`, () => {
    owner++; invalidateReads(); state.subledgerOpenings.value = []; state.subledgerPayments.value = []
    state.subledgerOptions.value = null; state.subledgerForm.value = emptyForm()
  }, { flush: 'sync' })
  // 网络波动只失效读取结果；同账号的未保存明细与档案标签继续保留。
  watch(state.connectionLost, invalidateReads, { flush: 'sync' })

  async function loadSubledger(): Promise<boolean> {
    if (!can('subledger_opening.view') || !connected()) return false
    const ticket = ++readTicket; const session = owner; const activity = ++loadingTicket
    clearReport(); state.subledgerLoading.value = true; state.subledgerOpenings.value = []; state.subledgerPayments.value = []
    try {
      const [records, payments, options] = await Promise.all([
        window.nexora!.callApi('subledgerOpenings', undefined), window.nexora!.callApi('subledgerPayments', undefined),
        can('subledger_opening.create') ? window.nexora!.callApi('subledgerOptions', undefined) : Promise.resolve(null)
      ])
      if (ticket !== readTicket || session !== owner || !can('subledger_opening.view')) return false
      state.subledgerOpenings.value = records; state.subledgerPayments.value = payments; state.subledgerOptions.value = options
      return true
    } catch (error) {
      if (ticket === readTicket && session === owner) state.subledgerError.value = displayError(error)
      return false
    } finally { if (activity === loadingTicket && session === owner) state.subledgerLoading.value = false }
  }
  async function querySubledger(): Promise<boolean> {
    if (!can('subledger_opening.view') || !connected() || state.subledgerLoading.value) return false
    clearReport()
    const ticket = ++queryTicket; const session = owner; const activity = ++loadingTicket
    const filters = { ...state.subledgerQuery.value }; state.subledgerLoading.value = true
    try {
      const report = await window.nexora!.callApi('querySubledger', filters)
      if (ticket !== queryTicket || session !== owner || !can('subledger_opening.view')) return false
      state.subledgerReport.value = report; return true
    } catch (error) {
      if (ticket === queryTicket && session === owner) state.subledgerError.value = displayError(error)
      return false
    } finally { if (activity === loadingTicket && session === owner) state.subledgerLoading.value = false }
  }
  async function refreshSubledgerApproval(): Promise<void> {
    // 方案与资金使用独立列表；审批变化后同步原版本，恢复已查询的同一截止日余额。
    const hadReport = !!state.subledgerReport.value
    if (await loadSubledger() && hadReport) await querySubledger()
  }
  async function editSubledger(item?: SubledgerOpening): Promise<boolean> {
    if (!can('subledger_opening.create') || !connected() || state.busy.value) return false
    const ticket = ++editTicket; const session = owner
    const options = await window.nexora!.callApi('subledgerOptions', undefined)
    if (ticket !== editTicket || session !== owner || !can('subledger_opening.create')) return false
    state.subledgerOptions.value = options
    state.subledgerForm.value = item ? {
      id: item.id, version: item.version, reference: item.reference, opening_balance_id: item.opening_balance_id,
      opening_version: item.opening_version, note: item.note, reason: '',
      control_accounts: item.control_accounts.map(({ kind, account_id }) => ({ kind, account_id })),
      lines: item.lines.map(({ kind, party_id, account_id, document_reference, document_date, debit, credit, auxiliary }) => ({
        kind, party_id, account_id, document_reference, document_date, debit, credit,
        auxiliary: auxiliary.filter(value => ['department','project'].includes(value.kind)).map(({ kind, id }) => ({ kind, id }))
      }))
    } : { ...emptyForm(), opening_balance_id: options.opening_balance?.id ?? 0, opening_version: options.opening_balance?.version ?? 0 }
    return true
  }
  async function write(permission: string, run: () => Promise<unknown>, message: string): Promise<boolean> {
    if (!can(permission) || !connected() || state.busy.value) return false
    const session = owner; let saved = false
    // 排队写操作在发送前重新检查原会话，不能把期初或资金写入另一个实例。
    await perform(async () => { if (session !== owner || !can(permission) || !connected()) throw new Error('会话或连接已变化，请重新打开分户方案。'); await run(); saved = session === owner && can(permission) }, message)
    if (!saved || session !== owner || !can(permission)) return false
    detailTicket++; state.subledgerChanges.value = []; state.subledgerCheck.value = null
    await loadSubledger()
    return session === owner && can(permission)
  }
  async function saveSubledger(): Promise<boolean> {
    const { id, version, reference, opening_balance_id, opening_version, note, reason, control_accounts, lines } = state.subledgerForm.value
    const input = { reference, opening_balance_id, opening_version, note, reason,
      control_accounts: control_accounts.map(item => ({ ...item })),
      // 表格会给行附加内部标记；请求只提取业务字段，避免将控件状态发送给服务端。
      lines: lines.map(({ kind, party_id, account_id, document_reference, document_date, debit, credit, auxiliary }) => ({
        kind, party_id, account_id, document_reference, document_date, debit, credit,
        auxiliary: auxiliary.map(({ kind, id }) => ({ kind, id })) })) }
    const saved = await write('subledger_opening.create', () => id === null
      ? window.nexora!.callApi('createSubledgerOpening', input)
      : window.nexora!.callApi('updateSubledgerOpening', { ...input, id, version }), '分户草稿已保存，须逐组合核对并由另一账号审核。')
    if (saved) state.subledgerForm.value = emptyForm()
    return saved
  }
  async function changeSubledgerStatus(item: SubledgerOpening, action: OpeningBalanceAction, reason: string): Promise<boolean> {
    if (['submit','approve','reject'].includes(action)) return false
    if (action === 'confirm' && item.approval?.status !== 'approved') return false
    if (action === 'reverse' && item.reversal_approval?.status !== 'approved') return false
    if (action === 'cancel' && ['submitted','approved'].includes(item.approval?.status ?? '')) return false
    const permission = ['approve','reject'].includes(action) ? 'subledger_opening.review' : `subledger_opening.${action}`
    return write(permission, () => window.nexora!.callApi('changeSubledgerStatus', { id: item.id, version: item.version, action, reason }), '分户期初状态已更新。')
  }
  async function loadSubledgerDetail(item: SubledgerOpening): Promise<boolean> {
    if (!can('subledger_opening.view') || !connected()) return false
    const ticket = ++detailTicket; const session = owner
    state.subledgerChanges.value = []; state.subledgerCheck.value = null
    try {
      const [changes, check] = await Promise.all([window.nexora!.callApi('subledgerChanges', { id: item.id }),
        item.evidence || ['cancelled','reversed'].includes(item.status) ? Promise.resolve(item.evidence)
          : window.nexora!.callApi('subledgerCheck', { id: item.id })])
      if (ticket !== detailTicket || session !== owner || !can('subledger_opening.view')) return false
      state.subledgerChanges.value = changes; state.subledgerCheck.value = check; return true
    } catch (error) { if (ticket === detailTicket && session === owner) state.subledgerError.value = displayError(error); return false }
  }
  async function exportSubledger(): Promise<void> {
    const report = state.subledgerReport.value
    if (!report || !can('subledger_opening.view') || !connected()) return
    const session = owner
    try {
      const saved = await window.nexora!.saveReportCsv(`subledger-${report.to_date}.csv`, report.csv)
      if (saved && session === owner && can('subledger_opening.view')) state.notice.value = '分户未结余额 CSV 已保存。'
    } catch (error) { if (session === owner) state.subledgerError.value = displayError(error) }
  }
  return { loadSubledger, refreshSubledgerApproval, querySubledger, editSubledger, saveSubledger, changeSubledgerStatus, loadSubledgerDetail, clearSubledgerDetail, exportSubledger,
    createSubledgerPayment: (input: SubledgerPaymentInput) => write('finance.record',
      () => window.nexora!.callApi('createSubledgerPayment', { ...input }), '分户资金草稿已保存，独立批准后执行才更新余额。'),
    changeSubledgerPaymentStatus: (item: SubledgerPayment, action: 'post' | 'cancel', reason: string) => {
      if (item.status !== 'draft' || action === 'post' && item.approval?.status !== 'approved'
        || action === 'cancel' && ['submitted','approved'].includes(item.approval?.status ?? '')) return Promise.resolve(false)
      // 排队发送前沿用实例、证书、账号及权限的会话复核，避免跨服务端写入。
      return write(item.reverses_id ? 'finance.reverse' : 'finance.record',
        () => window.nexora!.callApi('changeSubledgerPaymentStatus', { id: item.id, version: item.version, action, reason }),
        action === 'post' ? '分户资金已执行。' : '分户资金草稿已取消。')
    },
    reverseSubledgerPayment: (id: number, reason: string) => write('finance.reverse',
      () => window.nexora!.callApi('reverseSubledgerPayment', { id, reason }), '反向分户草稿已保存，仍须独立批准并执行。') }
}
