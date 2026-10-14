import { computed, inject, onScopeDispose, provide, shallowReactive, toValue } from 'vue'
import type { InjectionKey, MaybeRefOrGetter } from 'vue'
import { clearDialogOrigins } from '../utils/dialog-origin.ts'

export type DialogPresentationPhase = 'idle' | 'preparing' | 'opening' | 'open' | 'closing'
interface DialogPreparation { pending: MaybeRefOrGetter<boolean>; error?: MaybeRefOrGetter<string | null | undefined> }
export function createDialogPreparationBarrier() {
  const entries = shallowReactive(new Map<symbol, DialogPreparation>())
  return {
    pending: computed(() => [...entries.values()].some(entry => toValue(entry.pending))),
    error: computed(() => [...entries.values()].map(entry => entry.error ? toValue(entry.error) : '').find(Boolean) ?? ''),
    register(entry: DialogPreparation): () => void {
      const key = Symbol('dialog-preparation'); entries.set(key, entry)
      return () => entries.delete(key)
    }
  }
}
type DialogPreparationBarrier = ReturnType<typeof createDialogPreparationBarrier>
const preparationKey: InjectionKey<DialogPreparationBarrier> = Symbol('dialog-preparation')
export function provideDialogPreparation(): DialogPreparationBarrier {
  const barrier = createDialogPreparationBarrier(); provide(preparationKey, barrier); return barrier
}
export function useDialogPreparation(pending: MaybeRefOrGetter<boolean>, error?: MaybeRefOrGetter<string | null | undefined>): void {
  // 首屏历史组件在不可见的预布局阶段照常加载，只有所属窗口的全部屏障就绪后才展开。
  const barrier = inject(preparationKey, null)
  if (barrier) onScopeDispose(barrier.register({ pending, error }))
}
const invalidations = new Set<() => void>()
export function onDialogPresentationInvalidated(clear: () => void): () => void {
  invalidations.add(clear); return () => invalidations.delete(clear)
}
export function invalidateDialogPresentations(): void {
  // 退出、切换实例、撤权没有离场宽限期，所有仍在显示或等待的旧数据立即销毁。
  clearDialogOrigins()
  for (const clear of [...invalidations]) clear()
}
