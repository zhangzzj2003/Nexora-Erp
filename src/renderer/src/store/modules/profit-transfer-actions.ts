import { watch } from 'vue'
import type { ProfitTransferGenerateInput, ProfitTransferPolicy } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createProfitTransferActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let ticket = 0
  let owner = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  function clear(): void {
    state.profitTransferOptions.value = null
    state.profitTransferPreview.value = null
    state.profitTransferPolicyChanges.value = []
    state.profitTransferError.value = ''
  }
  watch(() => `${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    ticket++; owner++; clear(); state.profitTransferLoading.value = false
  }, { flush: 'sync' })
  async function read(id?: number): Promise<boolean> {
    if (!window.nexora || !can('profit_transfer.view') || state.connectionLost.value) return false
    const current = ++ticket
    state.profitTransferPreview.value = null
    state.profitTransferError.value = ''
    state.profitTransferLoading.value = true
    try {
      if (id !== undefined) {
        const preview = await window.nexora.callApi('profitTransferPreview', { id, paged:true })
        if (current !== ticket || !can('profit_transfer.view')) return false
        state.profitTransferPreview.value = preview
      } else {
        state.profitTransferOptions.value = null
        state.profitTransferPolicyChanges.value = []
        const [options, changes] = await Promise.all([
          window.nexora.callApi('profitTransferOptions', undefined),
          Promise.resolve([])
        ])
        if (current !== ticket || !can('profit_transfer.view')) return false
        state.profitTransferOptions.value = options
        state.profitTransferPolicyChanges.value = changes
      }
      return true
    } catch (error) {
      if (current === ticket) state.profitTransferError.value = displayError(error)
      return false
    } finally {
      if (current === ticket) state.profitTransferLoading.value = false
    }
  }
  async function write(permission: string, action: () => Promise<unknown>, success: string): Promise<boolean> {
    if (!window.nexora || !can(permission) || state.busy.value || state.connectionLost.value) return false
    const current = owner
    let saved = false
    await perform(async () => {
      await action()
      saved = current === owner && can(permission)
    }, success)
    if (!saved || current !== owner || !can(permission)) return false
    await read()
    return current === owner && can(permission)
  }
  return {
    loadProfitTransferOptions: () => read(),
    loadProfitTransferPreview: (id: number) => read(id),
    saveProfitTransferPolicy: (input: ProfitTransferPolicy & { reason: string }) => write('profit_transfer.configure',
      () => window.nexora!.callApi('saveProfitTransferPolicy', { version: input.version, start_date: input.start_date,
        target_account_id: input.target_account_id, cost_account_ids: [...input.cost_account_ids], reason: input.reason }),
      '损益结转配置已保存，已生成结转仍保留原科目范围。'),
    generateProfitTransfer: (input: ProfitTransferGenerateInput) => write('profit_transfer.generate',
      () => window.nexora!.callApi('generateProfitTransfer', { ...input }),
      '损益结转草稿已生成，请提交并由另一账号审核过账。')
  }
}
