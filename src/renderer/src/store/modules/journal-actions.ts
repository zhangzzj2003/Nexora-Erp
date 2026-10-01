import type { Journal, JournalAction } from '../../../../shared/erp-api'
import type { AppState } from '../state'

export function createJournalActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  async function editJournal(item?: Journal): Promise<void> {
    if (!window.nexora) throw new Error('请在桌面应用中建立凭证。')
    state.journalOptions.value = await window.nexora.callApi('journalOptions', undefined)
    state.journalForm.value = item ? {
      id: item.id, version: item.version, reference: item.reference, journal_date: item.journal_date,
      note: item.note, reason: '', lines: item.lines.map(({ account_id, summary, debit, credit, customer_id, supplier_id, department, project }) => ({ account_id, summary, debit, credit,
          ...(customer_id === undefined ? {} : {customer_id}), ...(supplier_id === undefined ? {} : {supplier_id}),
          ...(department === undefined ? {} : {department}), ...(project === undefined ? {} : {project}) }))
    } : { id: null, version: 1, reference: '', journal_date: '', note: '', reason: '',
      lines: [1, 2].map(() => ({ account_id: 0, summary: '', debit: '0', credit: '0' })) }
  }
  async function saveJournal(): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      const { id, version, reference, journal_date, note, reason, lines } = state.journalForm.value
      // 逐项构造普通对象，避免 Vue Proxy 进入 Electron IPC。
      const input = { reference, journal_date, note, reason,
        lines: lines.map(({ account_id, summary, debit, credit, customer_id, supplier_id, department, project }) => ({ account_id, summary, debit, credit,
          ...(customer_id === undefined ? {} : {customer_id}), ...(supplier_id === undefined ? {} : {supplier_id}),
          ...(department === undefined ? {} : {department}), ...(project === undefined ? {} : {project}) })) }
      if (id === null) await window.nexora!.callApi('createJournal', input)
      else await window.nexora!.callApi('updateJournal', { ...input, id, version })
      state.journalForm.value = { id: null, version: 1, reference: '', journal_date: '', note: '', reason: '', lines: [] }
      saved = true
    }, '凭证草稿已保存，提交后由另一账号审核。')
    return saved
  }
  async function changeJournalStatus(item: Journal, action: JournalAction, reason: string): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      await window.nexora!.callApi('changeJournalStatus', { id: item.id, version: item.version, action, reason })
      saved = true
    }, '凭证状态已更新。')
    return saved
  }
  async function reverseJournal(item: Journal, reference: string, journal_date: string, reason: string): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      await window.nexora!.callApi('reverseJournal', { id: item.id, version: item.version, reference, journal_date, reason })
      saved = true
    }, '冲销草稿已建立，审核并过账后才抵销原凭证。')
    return saved
  }
  async function loadJournalChanges(id: number) {
    if (!window.nexora) throw new Error('请在桌面应用中查看凭证记录。')
    return window.nexora.callApi('journalChanges', { id })
  }
  return { editJournal, saveJournal, changeJournalStatus, reverseJournal, loadJournalChanges }
}
