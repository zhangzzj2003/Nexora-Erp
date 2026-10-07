import { watch } from 'vue'
import type { AppState } from '../state'
import type { DocumentApprovalAction, DocumentApprovalTarget, DocumentApprovalRecord } from '../../../../shared/document-approval-api'
import { documentApprovalActionBody, documentApprovalTarget, validateDocumentApprovalRecord } from '../../../../shared/document-approval-api.ts'
import { displayError } from '../../utils/formatters.ts'

export function approvalTargetKey(target: DocumentApprovalTarget): string {
  return `${target.document_type}:${target.document_id}:${target.intent}`
}
export function createDocumentApprovalCaseActions(state: AppState, refreshData: () => Promise<void>, refreshDomain?: (target: DocumentApprovalTarget) => Promise<void>) {
  let owner = 0, reads = 0
  const available = () => !!window.nexora && !!state.user.value && !state.connectionLost.value
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles.join('|')}:${state.user.value?.permissions.join('|')}`, () => {
    // 单据意见只属于当前实例和人员；旧请求不得恢复退出前的弹窗。
    owner++; reads++
    state.documentApprovalTarget.value = null; state.documentApprovalRecord.value = null
    state.documentApprovalReasons.value = {}; state.documentApprovalError.value = ''
    state.documentApprovalLoading.value = false
  }, { flush: 'sync' })
  watch(state.connectionLost, () => {
    owner++; reads++; state.documentApprovalRecord.value = null
    state.documentApprovalLoading.value = false
    // 同实例断线保留意见草稿，重连后先刷新版本再允许操作。
  }, { flush: 'sync' })

  async function refreshBusiness(target: DocumentApprovalTarget, session: number): Promise<void> {
    await refreshData()
    // 领域列表采用自己的读取边界；退出或切换实例后不能再刷新旧单据详情。
    if (session === owner && available()) await refreshDomain?.(target)
  }
  function checked(record: DocumentApprovalRecord, target: DocumentApprovalTarget): void {
    validateDocumentApprovalRecord(record)
    if (approvalTargetKey(record) !== approvalTargetKey(target)) throw Error('审批结果与当前单据不一致。')
  }
  async function loadDocumentApproval(): Promise<boolean> {
    const target = state.documentApprovalTarget.value
    if (!available() || !target) return false
    const ticket = ++reads, session = owner, key = approvalTargetKey(target)
    state.documentApprovalLoading.value = true; state.documentApprovalError.value = ''
    state.documentApprovalRecord.value = null
    try {
      const result = await window.nexora!.callApi('documentApproval', { ...target })
      if (session !== owner || ticket !== reads || !available()
          || !state.documentApprovalTarget.value || approvalTargetKey(state.documentApprovalTarget.value) !== key) return false
      checked(result, target)
      // 他人在另一客户端完成审批后，刷新记录同时刷新原业务列表，不能继续显示旧的下一步动作。
      await refreshBusiness(target, session)
      if (session !== owner || ticket !== reads || !available()
          || !state.documentApprovalTarget.value || approvalTargetKey(state.documentApprovalTarget.value) !== key) return false
      state.documentApprovalRecord.value = result
      return true
    } catch (cause) {
      if (session === owner && ticket === reads) state.documentApprovalError.value = displayError(cause)
      return false
    } finally { if (session === owner && ticket === reads) state.documentApprovalLoading.value = false }
  }
  async function openDocumentApproval(target: DocumentApprovalTarget): Promise<boolean> {
    if (!available() || state.busy.value) return false
    state.documentApprovalTarget.value = documentApprovalTarget(target)
    state.documentApprovalRecord.value = null
    return loadDocumentApproval()
  }
  function closeDocumentApproval(): void {
    if (state.busy.value) return
    reads++; state.documentApprovalTarget.value = null; state.documentApprovalRecord.value = null
    state.documentApprovalLoading.value = false; state.documentApprovalError.value = ''
  }
  async function actDocumentApproval(action: DocumentApprovalAction): Promise<boolean> {
    const target = state.documentApprovalTarget.value, record = state.documentApprovalRecord.value
    if (!available() || !target || !record || state.busy.value || state.documentApprovalLoading.value) return false
    if (!(action === 'submit' ? record.can_submit : action === 'withdraw' ? record.can_withdraw : record.can_review)) return false
    const session = owner, key = approvalTargetKey(target)
    state.busy.value = true; reads++; state.documentApprovalError.value = ''
    try {
      const input = { ...target, action, version: record.version, reason: state.documentApprovalReasons.value[key] ?? '' }
      documentApprovalActionBody(input)
      const result = await window.nexora!.callApi('actDocumentApproval', input)
      if (session !== owner || !available()) return false
      checked(result, target)
      state.documentApprovalRecord.value = result
      await refreshBusiness(target, session)
      if (session !== owner || !available()) return false
      // 刷新失败也保留原输入；执行使用服务端固定冲销原因，审核意见不覆盖它。
      delete state.documentApprovalReasons.value[key]
      state.notice.value = action === 'approve' ? '审批步骤已完成。' : action === 'reject' ? '单据已驳回。'
        : action === 'withdraw' ? '审批已撤回。' : '单据已提交独立审批。'
      return true
    } catch (cause) {
      if (session === owner) {
        const message = displayError(cause)
        await loadDocumentApproval()
        if (session === owner) state.documentApprovalError.value = message
      }
      return false
    } finally { state.busy.value = false }
  }
  return { openDocumentApproval, closeDocumentApproval, loadDocumentApproval, actDocumentApproval }
}
