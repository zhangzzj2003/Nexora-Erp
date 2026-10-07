import { watch } from 'vue'
import type { MrpAction, MrpPlan, MrpPolicyInput } from '../../../../shared/mrp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createMrpActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let owner = 0; let reads = 0; let details = 0; let policyReads = 0
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  const available = () => !!window.nexora && !state.connectionLost.value
  function clearMrpDetail(): void { details++; state.mrpDetail.value = null; state.mrpCheck.value = null; state.mrpChanges.value = [] }
  function invalidate(): void {
    reads++; policyReads++; clearMrpDetail(); state.mrpLoading.value = false; state.mrpError.value = ''
    state.mrpPlans.value = []; state.mrpOptions.value = null; state.mrpPolicyChanges.value = []
  }
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`, () => {
    owner++; invalidate()
    state.mrpForm.value = { reference: '', start_date: '', reason: '', demand_dates: [], supply_dates: [], manual_demands: [] }
  }, { flush: 'sync' })
  // 断线使来源与批准检查失效，同账号未保存的输入继续保留。
  watch(state.connectionLost, () => { owner++; invalidate() }, { flush: 'sync' })
  async function loadMrp(): Promise<boolean> {
    if (!can('mrp.view') || !available() || state.mrpLoading.value) return false
    const ticket = ++reads; const session = owner
    state.mrpLoading.value = true; state.mrpError.value = ''; clearMrpDetail()
    try {
      const [records, options] = await Promise.all([window.nexora!.callApi('mrpPlans', undefined), window.nexora!.callApi('mrpOptions', undefined)])
      if (ticket !== reads || session !== owner || !can('mrp.view')) return false
      state.mrpPlans.value = records; state.mrpOptions.value = options
      state.mrpForm.value.start_date ||= options.today
      // 只在来源仍存在时保留日期；新增来源保持空日期，要求操作者明确安排。
      for (const [field, sources] of [['demand_dates', options.demands], ['supply_dates', options.supplies.filter(row => !row.due_date)]] as const) {
        const previous = new Map(state.mrpForm.value[field].map(row => [row.key, row.due_date]))
        state.mrpForm.value[field] = sources.map(row => ({ key: row.key, due_date: previous.get(row.key) ?? '' }))
      }
      return true
    } catch (error) {
      if (ticket === reads && session === owner) { state.mrpOptions.value = null; state.mrpPlans.value = []; state.mrpError.value = displayError(error) }
      return false
    } finally { if (ticket === reads && session === owner) state.mrpLoading.value = false }
  }
  async function loadMrpDetail(item: Pick<MrpPlan, 'id'>): Promise<boolean> {
    if (!can('mrp.view') || !available()) return false
    clearMrpDetail(); const ticket = details; const session = owner; state.mrpError.value = ''
    try {
      const [record, changes, check] = await Promise.all([window.nexora!.callApi('mrpDetail', { id: item.id }),
        window.nexora!.callApi('mrpChanges', { id: item.id }), window.nexora!.callApi('mrpCheck', { id: item.id })])
      if (ticket !== details || session !== owner || !can('mrp.view')) return false
      state.mrpDetail.value = record; state.mrpChanges.value = changes; state.mrpCheck.value = check; return true
    } catch (error) { if (ticket === details && session === owner) state.mrpError.value = displayError(error); return false }
  }
  async function refreshMrpApproval(id: number): Promise<void> {
    const session = owner, previous = state.mrpDetail.value, ticket = details
    if (!await loadMrp()) throw new Error('计划列表刷新失败，请重新读取。')
    // 审批刷新保留未保存编排；关闭或切换的详情不能被迟到响应重新打开。
    if (session === owner && details === ticket + 1 && previous?.id === id) {
      if (!await loadMrpDetail({ id })) throw new Error('计划详情刷新失败，请重新读取。')
    }
  }
  async function write(permission: string, run: () => Promise<unknown>, message: string, planId?: number): Promise<boolean> {
    if (!can(permission) || !available() || state.busy.value) return false
    const session = owner; let saved = false
    await perform(async () => {
      // 排队后再次核对账号、实例及连接，避免旧弹窗向新服务端写入。
      if (session !== owner || !can(permission) || !available()) return
      await run(); saved = session === owner && can(permission) && available()
    }, message)
    if (!saved || session !== owner || !can(permission)) return false
    await loadMrp()
    if (planId && session === owner) await loadMrpDetail({ id: planId })
    return session === owner && can(permission)
  }
  async function createMrpPlan(): Promise<boolean> {
    const { reference, start_date, reason, demand_dates, supply_dates, manual_demands } = state.mrpForm.value
    const input = { reference, start_date, reason, demand_dates: demand_dates.map(({ key, due_date }) => ({ key, due_date })),
      supply_dates: supply_dates.map(({ key, due_date }) => ({ key, due_date })),
      manual_demands: manual_demands.map(({ material_id, quantity, due_date, reference }) => ({ material_id, quantity, due_date, reference })) }
    let id: number | undefined
    const saved = await write('mrp.create', async () => { id = (await window.nexora!.callApi('createMrpPlan', input)).id }, '计划计算已固定，须核对并由另一账号审核。')
    if (saved) {
      state.mrpForm.value.reference = ''; state.mrpForm.value.reason = ''
      if (id) await loadMrpDetail({ id })
    }
    return saved
  }
  async function loadMrpPolicyChanges(id: number): Promise<boolean> {
    if (!can('mrp.view') || !available()) return false
    const ticket = ++policyReads; const session = owner; state.mrpPolicyChanges.value = []
    try {
      const changes = await window.nexora!.callApi('mrpPolicyChanges', { id })
      if (ticket !== policyReads || session !== owner) return false
      state.mrpPolicyChanges.value = changes; return true
    } catch (error) { if (ticket === policyReads && session === owner) state.mrpError.value = displayError(error); return false }
  }
  async function exportMrp(): Promise<void> {
    const item = state.mrpDetail.value; const session = owner
    if (!item || !can('mrp.view') || !available()) return
    try {
      if (await window.nexora!.saveReportCsv(`mrp-${item.id}.csv`, item.csv) && session === owner) state.notice.value = '固定计划 CSV 已保存。'
    } catch (error) { if (session === owner) state.mrpError.value = displayError(error) }
  }
  return { loadMrp, refreshMrpApproval, loadMrpDetail, clearMrpDetail, createMrpPlan, exportMrp, loadMrpPolicyChanges,
    saveMrpPolicy: (id: number, input: MrpPolicyInput) => write('mrp.configure', () => window.nexora!.callApi('saveMrpPolicy', { id, ...input }), '计划参数已保存，旧计划须重新计算。'),
    changeMrpStatus: (item: MrpPlan, action: MrpAction, reason: string) => write(['approve','reject'].includes(action) ? 'mrp.review' : `mrp.${action}`,
      () => window.nexora!.callApi('changeMrpStatus', { id: item.id, version: item.version, action, reason }), '计划状态已更新。', item.id),
    convertMrpSuggestion: (item: MrpPlan, suggestion_key: string, warehouse_id: number | null, reference: string, reason: string) => write('mrp.convert',
      () => window.nexora!.callApi('convertMrpSuggestion', { id: item.id, version: item.version, suggestion_key, warehouse_id, reference, reason }), '建议已转为原单草稿，须完成原单流程。', item.id) }
}
