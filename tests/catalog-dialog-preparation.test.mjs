import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createCatalogActions } from '../src/renderer/src/store/modules/catalog-actions.ts'

const cases = [
  { name: '物料编辑', read: actions => actions.loadMaterial(1), result: { id: 1, name: '新资料' },
    field: 'materials', initial: [{ id: 1, name: '旧资料' }], expected: [{ id: 1, name: '新资料' }] },
  { name: '分类编辑目录', read: actions => actions.reloadMaterialCategories(), result: [{ code: 'NEW' }],
    field: 'materialCategories', initial: [{ code: 'OLD' }], expected: [{ code: 'NEW' }] },
  { name: '分类变更详情', read: actions => actions.loadMaterialCategoryChanges('EL'), result: [{ id: 2 }],
    field: 'materialCategoryChanges', initial: [{ id: 1 }], expected: [{ id: 2 }] }
]
// 使用真实 store 的三条读取链，验证取消必须同时处理内容归属和全局忙碌锁。
for (const entry of cases) test(`${entry.name}稳定会话可读取，取消和换实例拒绝迟到结果且不释放新任务忙碌锁`, async t => {
  const previous = globalThis.window, state = createAppState(), scope = effectScope(), pending = []
  t.after(() => { scope.stop(); globalThis.window = previous })
  state.user.value = { id: 1, roles: ['catalog', 'viewer'], permissions: ['catalog.manage', 'catalog.view'] }
  state.server.value = { id: 'first', fingerprint: 'certificate' }
  state[entry.field].value = structuredClone(entry.initial)
  globalThis.window = { nexora: { callApi: () => new Promise((resolve, reject) => pending.push({ resolve, reject })) } }
  const actions = scope.run(() => createCatalogActions(state, action => action()))

  const stable = entry.read(actions)
  // 同一集合返回顺序变化也必须保持当前读取和忙碌归属。
  state.user.value = { ...state.user.value, roles: [...state.user.value.roles].reverse(), permissions: [...state.user.value.permissions].reverse() }
  state.server.value = { ...state.server.value }
  pending.shift().resolve(entry.result)
  assert.ok(await stable)
  assert.deepEqual(state[entry.field].value, entry.expected)
  assert.equal(state.busy.value, false)

  state.materialEditorDraft.value.name = '保留草稿'
  const cancelled = entry.read(actions)
  assert.equal(state.busy.value, true)
  actions.cancelCatalogPreparation()
  assert.equal(state.busy.value, false, '取消后立即允许重新选择入口')
  const newer = entry.read(actions)
  pending.shift().reject(new Error('已取消请求错误'))
  assert.ok(!(await cancelled))
  assert.equal(state.busy.value, true, '旧 finally 不能解锁新请求')
  assert.equal(state.error.value, '')
  pending.shift().resolve(entry.result)
  assert.ok(await newer)
  assert.equal(state.materialEditorDraft.value.name, '保留草稿')

  const switched = entry.read(actions)
  state.server.value.fingerprint = 'changed-in-place'
  assert.equal(state.busy.value, false)
  state.busy.value = true
  state.error.value = '新会话自己的反馈'
  pending.shift().reject(new Error('旧实例失败'))
  assert.ok(!(await switched))
  assert.equal(state.error.value, '新会话自己的反馈')
  assert.equal(state.busy.value, true)
  state.busy.value = false

  const revoked = entry.read(actions)
  state.user.value.permissions = []
  pending.shift().resolve(entry.result)
  assert.ok(!(await revoked))
  assert.equal(state.busy.value, false)
  state.user.value.permissions = ['catalog.manage']
  const displayed = state[entry.field].value
  const disconnected = entry.read(actions)
  state.connectionLost.value = true; state.connectionLost.value = false
  pending.shift().resolve(entry.result)
  assert.ok(!(await disconnected))
  assert.deepEqual(state[entry.field].value, displayed)
})
