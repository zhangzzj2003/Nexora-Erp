import { watch } from 'vue'
import type { AppState } from '../state'
import type { DocumentApprovalType } from '../../../../shared/document-approval-api'
import { documentApprovalPolicyBody } from '../../../../shared/document-approval-api.ts'
import { displayError } from '../../utils/formatters.ts'

export function createDocumentApprovalActions(state: AppState) {
  let owner = 0, reads = 0
  const available = () => !!window.nexora && !!state.user.value && !state.connectionLost.value
  const administrator = () => state.user.value?.roles.includes('admin') ?? false

  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles.join('|')}:${state.user.value?.permissions.join('|')}`, () => {
    // 退出、换账号、换实例或授权变化时失效旧请求，避免把草稿提交到另一数据库。
    owner++; reads++
    state.approvalPolicies.value = []; state.approvalPolicyDrafts.value = {}
    state.approvalPolicyLoading.value = false; state.approvalPolicyError.value = ''
  }, { flush: 'sync' })
  watch(state.connectionLost, () => {
    owner++; reads++
    state.approvalPolicies.value = []; state.approvalPolicyLoading.value = false
    // 同实例断线保留版本和正文，重连后必须重读服务端规则。
  }, { flush: 'sync' })

  async function loadApprovalPolicies(): Promise<boolean> {
    if (!available()) return false
    const ticket = ++reads, session = owner
    state.approvalPolicyLoading.value = true; state.approvalPolicyError.value = ''
    try {
      const rows = await window.nexora!.callApi('documentApprovalPolicies', undefined)
      if (ticket !== reads || session !== owner || !available()) return false
      state.approvalPolicies.value = rows
      return true
    } catch (cause) {
      if (ticket === reads && session === owner) state.approvalPolicyError.value = displayError(cause)
      return false
    } finally {
      if (ticket === reads && session === owner) state.approvalPolicyLoading.value = false
    }
  }

  function editApprovalPolicy(type: DocumentApprovalType, reset = false): boolean {
    if (!available() || !administrator() || state.busy.value) return false
    if (!reset && state.approvalPolicyDrafts.value[type]) return true
    const row = state.approvalPolicies.value.find(item => item.document_type === type)
    if (!row) return false
    state.approvalPolicyDrafts.value[type] = {
      document_type: type, version: row.version, steps: row.steps.map(step => ({ ...step }))
    }
    state.approvalPolicyError.value = ''
    return true
  }

  async function saveApprovalPolicy(type: DocumentApprovalType): Promise<boolean> {
    const draft = state.approvalPolicyDrafts.value[type]
    if (!available() || !administrator() || state.busy.value || !draft) return false
    const session = owner
    state.busy.value = true; state.approvalPolicyError.value = ''; reads++
    state.approvalPolicyLoading.value = false
    try {
      // 先冻结提交内容；失败保留原草稿，不把其他管理员的新规则静默覆盖进输入。
      const input = { document_type: type, ...documentApprovalPolicyBody(draft) }
      const saved = await window.nexora!.callApi('saveDocumentApprovalPolicy', input)
      if (session !== owner || !available() || !administrator()) return false
      if (saved.document_type !== type || saved.version !== input.version + 1) throw Error('审批模板保存结果不匹配，请重新读取。')
      reads++
      state.approvalPolicies.value = [...state.approvalPolicies.value.filter(row => row.document_type !== type), saved]
      state.approvalPolicyDrafts.value[type] = { document_type: type, version: saved.version,
        steps: saved.steps.map(step => ({ ...step })) }
      state.notice.value = '审批步骤已保存，只影响之后重新送审的单据。'
      return true
    } catch (cause) {
      if (session === owner) {
        const error = displayError(cause)
        await loadApprovalPolicies()
        if (session === owner) state.approvalPolicyError.value = error
      }
      return false
    } finally { state.busy.value = false }
  }
  return { loadApprovalPolicies, editApprovalPolicy, saveApprovalPolicy }
}
