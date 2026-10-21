import {computed, ref, toRaw, watch} from 'vue'
import type {Ref} from 'vue'
import type {SalesDraftState} from '../../../shared/sales-draft-api'
import {canReviseSalesDraft} from '../utils/sales-documents.ts'

export function useSalesDraftEditor<T extends object>(sharedForm: Ref<T>) {
  const open = ref(false), reason = ref('')
  const isolated = ref<T | null>(null) as Ref<T | null>
  const target = ref<{id: number; version: number} | null>(null)
  const form = computed(() => isolated.value ?? sharedForm.value)
  // 修订与从来源开单使用独立副本；关闭弹窗不会覆盖原先未保存的新建草稿。
  function beginEdit(row: SalesDraftState & {id: number; status: string; approval?: {status: string}}, values: T): boolean {
    if (!canReviseSalesDraft(row)) return false
    isolated.value = structuredClone(toRaw(values))
    target.value = {id: row.id, version: row.draft_version!}
    reason.value = ''
    open.value = true
    return true
  }
  function beginCreate(values: T): void {
    isolated.value = structuredClone(toRaw(values)); target.value = null; reason.value = ''; open.value = true
  }
  watch(open, value => {
    if (!value) { isolated.value = null; target.value = null; reason.value = '' }
  }, {flush:'sync'})
  return {open, form, target, reason, isolated, beginEdit, beginCreate}
}
