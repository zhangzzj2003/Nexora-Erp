import type { Journal, JournalAction, JournalAttachment, JournalAttachmentList } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { watch } from 'vue'

export function createJournalActions(state: AppState, perform: (action: () => Promise<unknown>, success: string) => Promise<void>) {
  let optionsTicket = 0
  const owner = () => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`
  watch(owner, () => {
    optionsTicket++
    state.journalOptions.value = { accounts: [], periods: [] }
    state.journalForm.value = { id: null, version: 1, reference: '', journal_date: '', note: '', reason: '', lines: [] }
  }, { flush: 'sync' })
  // 短暂断线只失效在途读取；已填写金额和辅助选择保留，提交由页面禁用。
  watch(state.connectionLost, () => { optionsTicket++ }, { flush: 'sync' })
  async function editJournal(item?: Journal): Promise<void> {
    if (!window.nexora) throw new Error('请在桌面应用中建立凭证。')
    const identity = owner(), ticket = ++optionsTicket
    const options = await window.nexora.callApi('journalOptions', undefined)
    // 旧会话的辅助档案与草稿不得在切换账号或撤权后重新出现。
    if (identity !== owner() || ticket !== optionsTicket) throw new Error('会话或权限已变化，请重新打开凭证。')
    state.journalOptions.value = options
    state.journalForm.value = item ? {
      id: item.id, version: item.version, reference: item.reference, journal_date: item.journal_date,
      note: item.note, reason: '', lines: item.lines.map(({ account_id, summary, debit, credit, auxiliary }) => ({ account_id, summary, debit, credit, ...(auxiliary ? { auxiliary: auxiliary.map(({ kind, id }) => ({ kind, id })) } : {}) }))
    } : { id: null, version: 1, reference: '', journal_date: '', note: '', reason: '',
      lines: [1, 2].map(() => ({ account_id: 0, summary: '', debit: '0', credit: '0' })) }
  }
  async function saveJournal(): Promise<boolean> {
    if (!window.nexora) return false
    const identity = owner()
    let saved = false
    await perform(async () => {
      const { id, version, reference, journal_date, note, reason, lines } = state.journalForm.value
      // 逐项构造普通对象，避免 Vue Proxy 进入 Electron IPC。
      const input = { reference, journal_date, note, reason,
        lines: lines.map(({ account_id, summary, debit, credit, auxiliary }) => ({ account_id, summary, debit, credit, ...(auxiliary ? { auxiliary: auxiliary.map(({ kind, id }) => ({ kind, id })) } : {}) })) }
      if (id === null) await window.nexora!.callApi('createJournal', input)
      else await window.nexora!.callApi('updateJournal', { ...input, id, version })
      if (identity !== owner()) return
      state.journalForm.value = { id: null, version: 1, reference: '', journal_date: '', note: '', reason: '', lines: [] }
      saved = true
    }, '凭证草稿已保存，提交后由另一账号审核。')
    return saved
  }
  async function changeJournalStatus(item: Journal, action: JournalAction, reason: string): Promise<boolean> {
    if (!window.nexora) return false
    // 审批动作只能走带独立审批版本的共用入口；旧调用不能产生看似成功的状态。
    if (['submit', 'approve', 'reject'].includes(action)) return false
    if (action === 'post' && item.approval?.status !== 'approved') return false
    if (action === 'cancel' && ['submitted', 'approved'].includes(item.approval?.status ?? '')) return false
    const identity = owner()
    let saved = false
    await perform(async () => {
      if (identity !== owner() || state.connectionLost.value) throw new Error('会话或连接已变化，请重新打开凭证。')
      await window.nexora!.callApi('changeJournalStatus', { id: item.id, version: item.version, action, reason })
      if (identity === owner()) saved = true
    }, '凭证状态已更新。')
    return saved
  }
  async function reverseJournal(item: Journal, reference: string, journal_date: string, reason: string): Promise<boolean> {
    if (!window.nexora) return false
    const identity = owner()
    let saved = false
    await perform(async () => {
      if (identity !== owner() || state.connectionLost.value) throw new Error('会话或连接已变化，请重新打开凭证。')
      await window.nexora!.callApi('reverseJournal', { id: item.id, version: item.version, reference, journal_date, reason })
      if (identity === owner()) saved = true
    }, '冲销草稿已建立，审核并过账后才抵销原凭证。')
    return saved
  }
  async function loadJournalChanges(id: number) {
    if (!window.nexora) throw new Error('请在桌面应用中查看凭证记录。')
    return window.nexora.callApi('journalChanges', { id })
  }
  async function loadJournalAttachments(id: number): Promise<JournalAttachmentList> {
    if (!window.nexora) throw new Error('请在桌面应用中查看凭证附件。')
    const identity = owner()
    const result = await window.nexora.callApi('journalAttachments', { id })
    if (identity !== owner()) throw new Error('会话或权限已变化，请重新读取凭证附件。')
    return result
  }
  async function uploadJournalAttachment(id: number, reason: string): Promise<JournalAttachment | null> {
    if (!window.nexora) throw new Error('请在桌面应用中上传凭证附件。')
    const identity = owner()
    const result = await window.nexora.uploadJournalAttachment(id, reason)
    if (identity !== owner()) throw new Error('会话或权限已变化，请重新读取凭证附件。')
    return result
  }
  async function reverseJournalAttachment(journalId: number, attachmentId: number,
      reason: string): Promise<JournalAttachment> {
    if (!window.nexora) throw new Error('请在桌面应用中撤销凭证附件。')
    const identity = owner()
    const result = await window.nexora.callApi('reverseJournalAttachment', { journalId, attachmentId, reason })
    if (identity !== owner()) throw new Error('会话或权限已变化，请重新读取凭证附件。')
    return result
  }
  async function saveJournalAttachment(journalId: number, attachmentId: number): Promise<string | null> {
    if (!window.nexora) throw new Error('请在桌面应用中导出凭证附件。')
    const identity = owner()
    const result = await window.nexora.saveJournalAttachment(journalId, attachmentId)
    if (identity !== owner()) throw new Error('会话或权限已变化，请重新读取凭证附件。')
    return result
  }
  return { editJournal, saveJournal, changeJournalStatus, reverseJournal, loadJournalChanges,
    loadJournalAttachments, uploadJournalAttachment, reverseJournalAttachment, saveJournalAttachment }
}
