import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createDataLoader } from '../src/renderer/src/store/data-loader.ts'

const admin = {
  id: 1,
  username: 'admin',
  is_active: true,
  roles: ['admin'],
  permissions: ['users.manage', 'inventory.view']
}
const permission = {
  code: 'bom.activate',
  label: '启用 BOM',
  group_path: [{ code: 'production', label: '生产管理' }, { code: 'bom', label: 'BOM' }]
}

test('业务列表返回 404 时，权限目录仍优先取得服务端数据', async (t) => {
  const originalWindow = globalThis.window
  t.after(() => { globalThis.window = originalWindow })
  const calls = []
  globalThis.window = { nexora: { async callApi(action) {
    calls.push(action)
    if (action === 'me') return admin
    if (action === 'permissions') return [permission]
    if (action === 'menuIcons') throw new Error('Not Found')
    return []
  } } }
  const state = createAppState()
  state.user.value = admin
  const can = (code) => state.user.value?.permissions.includes(code) ?? false
  const { refreshData } = createDataLoader(state, can, () => {})

  await assert.rejects(refreshData(), /Not Found/)
  assert.deepEqual(calls.slice(0, 2), ['me', 'permissions'])
  assert.deepEqual(state.permissions.value, [permission])
  assert.equal(state.permissionLabelDrafts.value['bom.activate'], '启用 BOM')
})

test('权限目录可独立重试；授权撤销后清除旧目录', async (t) => {
  const originalWindow = globalThis.window
  t.after(() => { globalThis.window = originalWindow })
  let unavailable = true
  let calls = 0
  globalThis.window = { nexora: { async callApi(action) {
    assert.equal(action, 'permissions')
    calls += 1
    if (unavailable) throw new Error('Not Found')
    return [permission]
  } } }
  const state = createAppState()
  state.user.value = admin
  const can = (code) => state.user.value?.permissions.includes(code) ?? false
  const { loadPermissions } = createDataLoader(state, can, () => {})

  await assert.rejects(loadPermissions(), /Not Found/)
  assert.deepEqual(state.permissions.value, [])
  unavailable = false
  await loadPermissions()
  assert.deepEqual(state.permissions.value, [permission])
  // 撤销管理权限时不再向服务端请求目录，也不保留以前的名称草稿。
  state.user.value = { ...admin, permissions: [] }
  await loadPermissions()
  assert.deepEqual(state.permissions.value, [])
  assert.deepEqual(state.permissionLabelDrafts.value, {})
  assert.equal(calls, 2)
})
