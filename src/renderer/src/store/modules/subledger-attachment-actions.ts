import { watch } from 'vue'
import type { AppState } from '../state'

export function createSubledgerAttachmentActions(state: AppState) {
  let generation = 0
  const identity = () => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions.join('|')}`
  watch(identity, () => { generation++ }, {flush:'sync'})
  watch(state.connectionLost, () => { generation++ }, {flush:'sync'})
  function guard(permission = 'subledger_opening.view'): () => void {
    const captured = generation
    function check(): void {
      if (!window.nexora || state.connectionLost.value || captured !== generation
        || !state.user.value?.permissions.includes('subledger_opening.view')
        || !state.user.value.permissions.includes(permission)) throw Error('会话、权限或连接已变化，请重新读取原单附件。')
    }
    check(); return check
  }
  return {
    async loadSubledgerAttachments(id: number, page = 1) {
      const check = guard()
      const result = await window.nexora!.callApi('subledgerAttachments',{id,page,page_size:50})
      check(); return result
    },
    async uploadSubledgerAttachment(id: number, version: number, lineId: number, reason: string) {
      const check = guard('subledger_opening.attachment')
      const result = await window.nexora!.uploadSubledgerAttachment(id,version,lineId,reason)
      check(); return result
    },
    async reverseSubledgerAttachment(id: number, version: number, attachmentId: number, reason: string) {
      const check = guard('subledger_opening.attachment')
      const result = await window.nexora!.callApi('reverseSubledgerAttachment',{id,opening_version:version,attachmentId,reason})
      check(); return result
    },
    async saveSubledgerAttachment(id: number, attachmentId: number) {
      const check = guard()
      const result = await window.nexora!.saveSubledgerAttachment(id,attachmentId)
      check(); return result
    }
  }
}
