import type { AppState } from './state'
import { captureSession } from './session-state.ts'
import { displayError } from '../utils/formatters.ts'

// 将写入结果和后续刷新分开：刷新失败不能让用户再次提交已经成功的单据。
export function createBusinessOperation(
  state: AppState,
  refreshData: () => Promise<void>,
  captureApprovalRefresh: () => () => Promise<unknown>
) {
  return async (action: () => Promise<unknown>, success: string): Promise<void> => {
    if (state.busy.value) return
    if (state.connectionLost.value) {
      state.error.value = '服务端连接已中断，恢复连接后才能保存更改。'
      return
    }
    const current = captureSession(state)
    const refreshApproval = captureApprovalRefresh()
    state.busy.value = true
    state.error.value = ''; state.notice.value = ''; state.warning.value = ''
    let saved = false
    try {
      await action()
      saved = true
      if (!current()) return
      state.notice.value = success
      try { await refreshData() } catch (cause) {
        if (current()) state.warning.value = `操作已完成，但数据刷新失败，请刷新查看，勿重复提交。${displayError(cause)}`
      }
    } catch (cause) {
      if (current()) state.error.value = displayError(cause)
    } finally {
      // 无论写入成功还是冲突，都核对原详情；旧会话不得刷新新账号的审批或消息。
      try {
        if (current()) await refreshApproval()
      } catch (cause) {
        if (current() && saved) state.warning.value = `操作已完成，但审批详情刷新失败，请重新打开详情。${displayError(cause)}`
        else if (current() && !state.error.value) state.error.value = displayError(cause)
      } finally { state.busy.value = false }
    }
  }
}
