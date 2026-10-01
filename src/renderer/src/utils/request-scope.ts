import { watch } from 'vue'
import type { AppState } from '../store/state'

// 用递增序号识别撤权后又授权的情况；只比较账号编号会误接收旧请求。
export function createRequestScope(state: AppState) {
  let revision = 0
  watch(() => `${state.user.value?.id}:${state.user.value?.roles?.join('|')}:${state.user.value?.permissions?.join('|')}`,
    () => { revision++ }, { flush: 'sync' })
  return { capture: () => revision, current: (value: number) => value === revision }
}
