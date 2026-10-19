import { isReadonly, toRaw, watch } from 'vue'
import type { Ref } from 'vue'
import type { AppState } from './state'

const revisions = new WeakMap<object, number>()

// 这些字段描述窗口、连接和登录过程；其余可写状态默认属于当前业务会话。
const retainedKeys = new Set<keyof AppState>([
  'screen', 'version', 'busy', 'user', 'username', 'password', 'server', 'candidate',
  'recentServers', 'discoveries', 'scanSeconds', 'scanning', 'manualForm', 'hostForm',
  'trustChecked', 'host', 'connectionLost', 'connectionNotice'
])

export function initializeSessionState(state: AppState): void {
  revisions.set(state, 0)
  // 保存初始值而不是再次创建 store，避免生成额外监听器；每次重置使用独立草稿。
  const resets = Object.entries(state).flatMap(([key, cell]) => {
    if (retainedKeys.has(key as keyof AppState) || isReadonly(cell)) return []
    const target: Ref<unknown> = cell
    const initial = structuredClone(toRaw(target.value))
    return [() => { target.value = structuredClone(initial) }]
  })
  watch(() => ({
    owner: JSON.stringify([state.server.value?.id, state.server.value?.fingerprint, state.user.value?.id,
      state.user.value?.roles?.slice().sort()]),
    permissions: state.user.value?.permissions?.slice().sort() ?? []
  }), (next, previous) => {
    if (next.owner === previous.owner && JSON.stringify(next.permissions) === JSON.stringify(previous.permissions)) return
    // 所有授权变化都取消在途响应，但单纯增权或撤销操作按钮不应清空仍有权查看的表单。
    revisions.set(state, (revisions.get(state) ?? 0) + 1)
    const narrowed = previous.permissions.some(permission => !next.permissions.includes(permission)
      && /\.(view|view_all|cost|manage)$/.test(permission))
    if (next.owner !== previous.owner || narrowed) for (const reset of resets) reset()
  }, { flush: 'sync' })
}

export function captureSession(state: AppState): () => boolean {
  const revision = revisions.get(state)
  return () => revisions.get(state) === revision
}

// 过期读取不能作为成功刷新继续执行，也不能将旧请求错误显示给新的会话。
export class StaleSessionRead extends Error {
  constructor() { super('会话或刷新已变化，请重新读取当前数据。') }
}
