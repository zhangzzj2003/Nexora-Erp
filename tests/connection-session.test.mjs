import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createConnectionActions } from '../src/renderer/src/store/connection-actions.ts'

// 用隔离的窗口桥接模拟页面重建，不读取或修改用户现有的桌面会话。
const profile = {
  id: 'server-a', name: '测试主机', host: '192.168.3.5', port: 8000,
  fingerprint: 'fingerprint', version: '0.1.0', isLocal: false
}
const admin = {
  id: 1, username: 'admin', is_active: true,
  roles: ['admin'], permissions: ['inventory.view']
}

test('刷新后从服务端核验并恢复用户，再读取工作台数据', async (t) => {
  const previousWindow = globalThis.window
  t.after(() => { globalThis.window = previousWindow })
  const calls = []
  globalThis.window = { nexora: {
    async startup() { calls.push('startup'); return { status: 'connected', server: profile } },
    async callApi(action) { calls.push(action); if (action === 'documentNumbering') return { configured: true }; assert.equal(action, 'me'); return admin },
    async recentServers() { return [profile] },
    async hostStatus() { return { configured: false, running: false } }
  } }
  const state = createAppState()
  const actions = createConnectionActions(state, async () => { calls.push('refreshData') })

  await actions.checkConnection()

  assert.deepEqual(calls, ['startup', 'me', 'documentNumbering', 'refreshData'])
  assert.deepEqual(state.user.value, admin)
  assert.equal(state.screen.value, 'app')
  assert.equal(state.busy.value, false)
})

test('没有会话或会话失效时回到登录页，不读取业务数据', async (t) => {
  const previousWindow = globalThis.window
  t.after(() => { globalThis.window = previousWindow })
  for (const message of ['请先登录', '登录已失效，请重新登录']) {
    let refreshCount = 0
    globalThis.window = { nexora: {
      async startup() { return { status: 'connected', server: profile } },
      async callApi(action) { assert.equal(action, 'me'); throw new Error(message) },
      async recentServers() { return [profile] },
      async hostStatus() { return { configured: false, running: false } }
    } }
    const state = createAppState()
    const actions = createConnectionActions(state, async () => { refreshCount += 1 })

    await actions.checkConnection()

    assert.equal(state.user.value, null)
    assert.equal(state.screen.value, 'login')
    assert.equal(state.error.value, message === '请先登录' ? '' : message)
    assert.equal(refreshCount, 0)
  }
})

test('业务数据读取失败仍保留已核验账号并显示错误', async (t) => {
  const previousWindow = globalThis.window
  t.after(() => { globalThis.window = previousWindow })
  globalThis.window = { nexora: {
    async startup() { return { status: 'connected', server: profile } },
    async callApi(action) { if (action === 'documentNumbering') return { configured: true }; assert.equal(action, 'me'); return admin },
    async recentServers() { return [profile] },
    async hostStatus() { return { configured: false, running: false } }
  } }
  const state = createAppState()
  const actions = createConnectionActions(state, async () => { throw new Error('数据读取失败') })

  await actions.checkConnection()

  assert.deepEqual(state.user.value, admin)
  assert.equal(state.screen.value, 'app')
  assert.equal(state.error.value, '数据读取失败')
})
