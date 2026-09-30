import { watch } from 'vue'
import type { BusinessJournalGenerateInput, BusinessJournalPolicy } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

export function createBusinessJournalActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let ticket = 0
  let owner = 0
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  function clear(): void {
    state.businessJournalSources.value = []
    state.businessJournalOptions.value = null
    state.businessJournalPolicyChanges.value = []
    state.businessJournalError.value = ''
  }
  watch(() => `${state.user.value?.id}:${state.user.value?.permissions.join('|')}`, () => {
    ticket++; owner++; clear(); state.businessJournalLoading.value = false
  }, { flush: 'sync' })
  async function loadBusinessJournals(): Promise<boolean> {
    if (!window.nexora || !can('business_journal.view') || state.connectionLost.value) return false
    const current = ++ticket
    clear(); state.businessJournalLoading.value = true
    try {
      const [sources, options, changes] = await Promise.all([
        window.nexora.callApi('queryTable', { dataset:'businessSources',page:1,page_size:20,query:'' }),
        window.nexora.callApi('businessJournalOptions', undefined),
        Promise.resolve([])
      ])
      if (current !== ticket || !can('business_journal.view')) return false
      state.businessJournalSources.value = sources.items as unknown as typeof state.businessJournalSources.value
      state.businessJournalOptions.value = options
      state.businessJournalPolicyChanges.value = changes
      return true
    } catch (error) {
      if (current === ticket) state.businessJournalError.value = displayError(error)
      return false
    } finally {
      if (current === ticket) state.businessJournalLoading.value = false
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
    await loadBusinessJournals()
    return current === owner && can(permission)
  }
  return { loadBusinessJournals,
    saveBusinessJournalPolicy: (input: BusinessJournalPolicy & { reason: string }) => write('business_journal.configure',
      () => window.nexora!.callApi('saveBusinessJournalPolicy', { version: input.version, start_date: input.start_date, mapping: { ...input.mapping }, reason: input.reason }), '业务科目配置已保存，已生成凭证仍保留原配置快照。'),
    generateBusinessJournal: (input: BusinessJournalGenerateInput) => write('business_journal.generate',
      () => window.nexora!.callApi('generateBusinessJournal', { ...input }), '业务凭证草稿已生成，请在凭证列表提交并由另一账号审核。') }
}
