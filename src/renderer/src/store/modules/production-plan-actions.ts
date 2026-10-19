import { watch } from 'vue'
import type { AppState } from '../state'
import type { ProductionPlan, ProductionPlanDetail, ProductionPlanReleaseInput } from '../../../../shared/production-plan-api'
import { productionPlanBody } from '../../../../shared/production-plan-api.ts'
import { displayError } from '../../utils/formatters.ts'

export function createProductionPlanActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let owner = 0, reads = 0, details = 0
  const can = (permission: string) => state.user.value?.permissions.includes(permission) ?? false
  const available = () => !!window.nexora && !state.connectionLost.value
  function clearProductionPlanDetail(): void { details++; state.productionPlanDetail.value = null }
  function clearRead(): void {
    reads++; clearProductionPlanDetail(); state.productionPlans.value = []; state.productionPlanOptions.value = null
    state.productionPlanLoading.value = false; state.productionPlanError.value = ''
  }
  function resetProductionPlanForm(): void {
    state.productionPlanEdit.value = null
    state.productionPlanForm.value = { reference: '', note: '', reason: '', lines: [] }
  }
  // 草稿属于账号与实例；同账号断线保留输入，换号和撤权清除全部敏感数据。
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`, () => {
    owner++; clearRead(); resetProductionPlanForm()
  }, { flush: 'sync' })
  watch(state.connectionLost, () => { owner++; clearRead() }, { flush: 'sync' })
  async function loadProductionPlans(): Promise<boolean> {
    if (!available() || !can('production_plan.view')) return false
    const ticket = ++reads, session = owner
    state.productionPlanLoading.value = true; state.productionPlanError.value = ''
    try {
      const [records, options] = await Promise.all([window.nexora!.callApi('productionPlans', undefined), window.nexora!.callApi('productionPlanOptions', undefined)])
      if (ticket !== reads || session !== owner) return false
      state.productionPlans.value = records; state.productionPlanOptions.value = options; return true
    } catch (cause) {
      if (ticket === reads && session === owner) {
        state.productionPlans.value = []; state.productionPlanOptions.value = null; clearProductionPlanDetail()
        state.productionPlanError.value = displayError(cause)
      }
      return false
    } finally { if (ticket === reads && session === owner) state.productionPlanLoading.value = false }
  }
  async function loadProductionPlanDetail(id: number): Promise<boolean> {
    if (!available() || !can('production_plan.view')) return false
    clearProductionPlanDetail(); const ticket = details, session = owner
    state.productionPlanError.value = ''
    try {
      const result = await window.nexora!.callApi('productionPlanDetail', { id })
      if (ticket !== details || session !== owner) return false
      state.productionPlanDetail.value = result; return true
    } catch (cause) {
      if (ticket === details && session === owner) state.productionPlanError.value = displayError(cause)
      return false
    }
  }
  async function refreshProductionPlanApproval(id: number): Promise<void> {
    const session = owner, active = state.productionPlanDetail.value?.id
    if (!await loadProductionPlans()) throw Error('生产计划刷新失败，请重新读取')
    if (session === owner && active === id && state.productionPlanDetail.value?.id === id && !await loadProductionPlanDetail(id)) throw Error('计划详情刷新失败')
  }
  async function write(permission: string, run: () => Promise<ProductionPlanDetail>, message: string): Promise<boolean> {
    if (!available() || !can(permission) || state.busy.value) return false
    const session = owner; let saved: ProductionPlanDetail | undefined
    await perform(async () => {
      // 排队写入必须再次核对权限与会话，迟到成功不能清空另一账号的新草稿。
      if (session !== owner || !available() || !can(permission)) return
      saved = await run()
    }, message)
    if (!saved || session !== owner || !available() || !can(permission)) return false
    const id = saved.id
    await loadProductionPlans()
    if (session !== owner) return false
    await loadProductionPlanDetail(id)
    return session === owner
  }
  async function saveProductionPlan(): Promise<boolean> {
    let input
    try { input = productionPlanBody(state.productionPlanForm.value) }
    catch (cause) { state.productionPlanError.value = displayError(cause); return false }
    const edit = state.productionPlanEdit.value
    const saved = await write('production_plan.create', () => edit
      ? window.nexora!.callApi('updateProductionPlan', { ...input, ...edit })
      : window.nexora!.callApi('createProductionPlan', input), '生产计划草稿已保存，审批后可分批下达。')
    if (saved) resetProductionPlanForm()
    return saved
  }
  function editProductionPlan(plan: ProductionPlanDetail): boolean {
    if (!plan.can_edit || !can('production_plan.create') || !available()) return false
    state.productionPlanForm.value = productionPlanBody(plan)
    state.productionPlanForm.value.reason = ''
    state.productionPlanEdit.value = { id: plan.id, version: plan.version }
    return true
  }
  return { loadProductionPlans, loadProductionPlanDetail, clearProductionPlanDetail, resetProductionPlanForm,
    refreshProductionPlanApproval, saveProductionPlan, editProductionPlan,
    cancelProductionPlan: (plan: ProductionPlan, reason: string) => write('production_plan.cancel',
      () => window.nexora!.callApi('cancelProductionPlan', { id: plan.id, version: plan.version, reason }), '生产计划已取消，原记录保留。'),
    releaseProductionPlan: (input: ProductionPlanReleaseInput) => {
      if (!can('work_order.create')) return Promise.resolve(false)
      // 明确复制弹窗打开时的版本，刷新后不能把旧数量套用到其他计划。
      const request = { ...input }
      return write('production_plan.release', () => {
        if (!can('work_order.create')) throw Error('当前账号已失去工单建单权限')
        return window.nexora!.callApi('releaseProductionPlan', request)
      }, '已生成生产工单草稿，请在工单中独立审批并下达。')
    } }
}
