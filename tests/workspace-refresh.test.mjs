import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { createWorkspaceRefresh } from '../src/renderer/src/store/workspace-refresh.ts'

// 控制读取完成时机，验证切页和身份变化，不用依赖网络或动画定时。
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function setup() {
  const state = { context: { session: 'server:admin', path: '/workspace/stock' }, blocked: false,
    loading: false, reads: 0, remounts: 0, errors: [], events: [], gate: deferred() }
  const controller = createWorkspaceRefresh({
    context: () => state.context,
    blocked: () => state.blocked,
    setLoading: value => { state.loading = value; state.events.push(`loading:${value}`) },
    reloadData: async () => { state.reads++; await state.gate.promise; state.events.push('data') },
    remountPage: async () => { state.remounts++; state.events.push('page') },
    reportError: cause => state.errors.push(cause.message)
  })
  return { state, controller }
}

test('先取得新数据再重载页面，完成后释放忙碌状态', async () => {
  const { state, controller } = setup()
  const result = controller.refresh()
  assert.equal(state.loading, true)
  assert.equal(state.remounts, 0)
  state.gate.resolve()
  await result
  assert.deepEqual(state.events, ['loading:true', 'data', 'page', 'loading:false'])
  assert.equal(state.context.path, '/workspace/stock')
  assert.equal(state.context.session, 'server:admin')
})
test('连续点击只读取一次，业务忙碌、断线或未登录时不刷新', async () => {
  const { state, controller } = setup()
  const first = controller.refresh()
  await controller.refresh()
  assert.equal(state.reads, 1)
  state.gate.resolve()
  await first
  state.blocked = true
  await controller.refresh()
  state.blocked = false
  state.context = undefined
  await controller.refresh()
  assert.equal(state.reads, 1)
})
test('失败显示错误、保留当前页面且允许再次刷新', async () => {
  const { state, controller } = setup()
  const first = controller.refresh()
  state.gate.reject(new Error('服务端不可用'))
  await first
  assert.equal(state.loading, false)
  assert.equal(state.remounts, 0)
  assert.deepEqual(state.errors, ['服务端不可用'])
  state.gate = deferred()
  state.gate.resolve()
  await controller.refresh()
  assert.equal(state.reads, 2)
  assert.equal(state.remounts, 1)
})
for (const change of ['path', 'session', 'logout', 'dispose']) {
  test(`刷新期间${change}变化后不重载其他页面或显示旧错误`, async () => {
    const { state, controller } = setup()
    const first = controller.refresh()
    if (change === 'logout') state.context = undefined
    else if (change === 'dispose') controller.dispose()
    else state.context = { ...state.context, [change]: 'changed' }
    state.gate.resolve()
    await first
    assert.equal(state.remounts, 0)
    assert.equal(state.loading, false)
    state.gate = deferred()
    const second = controller.refresh()
    state.context = undefined
    state.gate.reject(new Error('旧会话失败'))
    // 无会话/销毁时没有读取者；提前订阅模拟请求以免产生未处理拒绝。
    void state.gate.promise.catch(() => {})
    await second
    assert.deepEqual(state.errors, [])
  })
}

test('异步读取期间禁用退出和切换服务端，避免旧响应写回其他身份', () => {
  // 原有加载器共享当前会话，刷新忙碌时身份入口必须保持锁定。
  for (const [file, action] of [
    ['components/workspace/SidebarAccountCard.vue', 'logout'],
    ['views/WorkspaceShell.vue', 'logout'],
    ['views/workspace/system/ConnectionSettingsView.vue', 'switchServer']
  ]) {
    const source = readFileSync(new URL(`../src/renderer/src/${file}`, import.meta.url), 'utf8')
    assert.match(source, new RegExp(`<AppButton[^>]*:disabled="busy"[^>]*@click="${action}"`))
  }
})
