import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { callBackend } from '../src/main/backend.ts'
import { createWarehouseActions } from '../src/renderer/src/store/modules/warehouse-actions.ts'

// 校验真实受限桥接的固定路径和输入边界，避免把无效名称转发到网络。
test('仓库编码预览限定名称和固定接口', async t => {
  const original = process.env.NEXORA_API_URL
  t.after(() => { if (original === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = original })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ path: url.pathname, method: options.method, body: JSON.parse(options.body ?? '{}') })
    return Response.json(url.pathname.endsWith('/login') ? { token: 'fixture', user: { id: 1 } } : { code: 'YCLCK' })
  })
  await callBackend('login', {})
  assert.deepEqual(await callBackend('previewWarehouseCode', { name: ' 原材料仓库 ', path: '/users' }), { code: 'YCLCK' })
  assert.deepEqual(calls.at(-1), { path: '/api/v1/warehouse-code-preview', method: 'POST', body: { name: '原材料仓库' } })
  const count = calls.length
  for (const input of [undefined, null, {}, { name: '' }, { name: '   ' }, { name: 42 }, { name: 'A'.repeat(81) }]) {
    await assert.rejects(callBackend('previewWarehouseCode', input), /仓库名称无效/)
  }
  assert.equal(calls.length, count)
})

// 服务端异常响应不能把负数、字符串或残缺编码带入表单和列表。
test('仓库新增参数及编码、种数响应在主进程校验', async t => {
  const original = process.env.NEXORA_API_URL
  t.after(() => { if (original === undefined) delete process.env.NEXORA_API_URL; else process.env.NEXORA_API_URL = original })
  process.env.NEXORA_API_URL = 'http://127.0.0.1:8123'
  let output, sent
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    sent = JSON.parse(options.body ?? '{}')
    return Response.json(url.pathname.endsWith('/login') ? { token: 'fixture', user: { id: 1 } } : output)
  })
  await callBackend('login', {})
  output = { id: 2, name: '东仓', code: 'DC', version: 1 }
  await callBackend('createWarehouse', { name: ' 东仓 ', extra: '不转发' })
  assert.deepEqual(sent, { name: '东仓' })
  await assert.rejects(callBackend('createWarehouse', { name: '东仓', code: '中文' }), /仓库编码无效/)
  await assert.rejects(callBackend('createWarehouse', { name: ' ' }), /仓库名称无效/)
  for (const bad of [null, {}, { code: 42 }, { code: '中文' }, { code: 'A'.repeat(41) }]) {
    output = bad
    await assert.rejects(callBackend('previewWarehouseCode', { name: '东仓' }), /预览响应无效/)
  }
  for (const bad of [-1, 0.5, '2', null, Number.MAX_SAFE_INTEGER + 1]) {
    output = [{ material_count: bad }]
    await assert.rejects(callBackend('warehouses'), /物料种数响应无效/)
  }
  for (const row of [{}, { material_count: 0 }, { material_count: 2 }]) {
    output = [row]
    assert.deepEqual(await callBackend('warehouses'), output)
  }
})

// 新建不能提交预览值，编辑保留原编码；写入失败应保留表单并返回失败。
test('仓库写入以服务端编码为准，失败保留草稿，断线不请求预览', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  const calls = [], state = { connectionLost: ref(false) }
  let fail = false
  globalThis.window = { nexora: { callApi: async (action, payload) => {
    if (fail) throw Error('编码冲突')
    calls.push([action, structuredClone(payload)])
    return { code: 'YCLCK' }
  } } }
  const actions = createWarehouseActions(state, async action => { try { await action() } catch { /* 模拟全局反馈保留草稿。 */ } })
  const draft = { name: '原材料仓库', code: '过期预览值', version: 0, reason: '' }
  assert.equal(await actions.previewWarehouseCode(draft.name), 'YCLCK')
  assert.equal(await actions.saveWarehouse(draft), true)
  assert.deepEqual(calls.at(-1), ['createWarehouse', { name: '原材料仓库' }])
  assert.equal(draft.code, '过期预览值')
  assert.equal(await actions.saveWarehouse({ code: 'MAIN', name: '更名主仓', version: 1, reason: '更名' }, 1), true)
  assert.deepEqual(calls.at(-1), ['updateWarehouse', { code: 'MAIN', name: '更名主仓', version: 1, reason: '更名', id: 1 }])
  fail = true
  assert.equal(await actions.saveWarehouse(draft), false)
  assert.equal(draft.name, '原材料仓库')
  state.connectionLost.value = true
  await assert.rejects(actions.previewWarehouseCode('东仓'), /连接已断开/)
})
