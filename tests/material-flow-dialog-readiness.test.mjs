import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia } from 'pinia'

let server, useApp, useFlow
before(async () => {
  // 测试真实领域 store，只隔离账号容器与桌面桥；每条请求都可以独立控制成功、失败和返回先后。
  server = await createServer({ configFile: false, plugins: [{
    name: 'material-flow-dialog-readiness', enforce: 'pre',
    resolveId(id, importer) {
      if (importer?.endsWith('/material-flow-store.ts') && id === '../app-store') return '\0flow-dialog-app'
    },
    load(id) {
      if (id === '\0flow-dialog-app') return `import {defineStore} from 'pinia';import {ref} from 'vue';
        export const usePiniaAppStore=defineStore('flow-dialog-app',()=>{
          const user=ref(null);
          return {user,server:ref(null),connectionLost:ref(false),busy:ref(false),notice:ref(''),
            can:code=>user.value?.permissions.includes(code)??false,refreshData:async()=>{}};
        });`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  ;({ usePiniaAppStore: useApp } = await server.ssrLoadModule('\0flow-dialog-app'))
  ;({ useMaterialFlowStore: useFlow } = await server.ssrLoadModule('/src/renderer/src/store/modules/material-flow-store.ts'))
})
after(() => server?.close())
const target = { kind: 'receipt', id: 7 }
const receipt = version => ({ ...target, version, document_no: 'SCLL-7', work_order_id: 2, warehouse_id: 1, lines: [], executions: [] })
const order = marker => ({ work_order_id: 2, marker, lines: [], sources: [], dispatches: [], receipts: [], exchanges: [], returns: [] })
function fixture(t) {
  const previous = globalThis.window, pending = [], pinia = createPinia(), app = useApp(pinia)
  app.user = { id: 1, roles: ['warehouse', 'production'], permissions: ['material_flow.view', 'material_receipt.sign'] }
  app.server = { id: 'first', fingerprint: 'certificate' }
  globalThis.window = { nexora: { callApi: (action, input) => new Promise((resolve, reject) => pending.push({ action, input, resolve, reject })) } }
  const flow = useFlow(pinia)
  t.after(() => { flow.$dispose(); app.$dispose(); globalThis.window = previous })
  return { app, flow, pending }
}
const reads = [
  { name: '详情', key: flow => flow.key(target), load: flow => flow.loadDocument(target), result: receipt,
    displayed: flow => flow.documents[flow.key(target)] },
  { name: '工单依据', key: flow => flow.orderKey(2), load: flow => flow.loadOrder(2), result: order,
    displayed: flow => flow.orders[2] },
  { name: '批次', key: flow => flow.lotsKey(target), load: flow => flow.loadLots(target), result: marker => ({ marker, lines: [] }) }
]

for (const entry of reads) test(`物料流转${entry.name}就绪以真实成功为准，失败和取消保留缓存并隔离迟到响应`, async t => {
  const { flow, pending } = fixture(t), scope = entry.key(flow)
  const initial = entry.load(flow)
  assert.equal(flow.loading[scope], true); assert.equal(flow.readReady[scope], false)
  pending.shift().resolve(entry.result(1))
  assert.deepEqual(await initial, entry.result(1)); assert.equal(flow.readReady[scope], true)
  const displayed = entry.displayed?.(flow)
  const failed = entry.load(flow)
  assert.equal(entry.displayed?.(flow), displayed); assert.equal(flow.readReady[scope], false)
  pending.shift().reject(Error('读取失败'))
  assert.equal(await failed, undefined); assert.match(flow.readErrors[scope], /读取失败/)
  assert.equal(entry.displayed?.(flow), displayed); assert.equal(flow.loading[scope], false)

  const cancelled = entry.load(flow)
  flow.cancelRead(scope)
  assert.equal(flow.readReady[scope], false); assert.equal(flow.loading[scope], false); assert.equal(flow.readErrors[scope], '')
  assert.equal(entry.displayed?.(flow), displayed)
  const reopened = entry.load(flow)
  pending.shift().reject(Error('被取消的请求报错'))
  assert.equal(await cancelled, undefined)
  assert.equal(flow.loading[scope], true); assert.equal(flow.readErrors[scope], '', '旧错误不能覆盖新等待')
  pending.shift().resolve(entry.result(2))
  assert.deepEqual(await reopened, entry.result(2)); assert.equal(flow.readReady[scope], true)
})

test('物料流转不同 key 的错误互不覆盖，取消详情同步取消其批次读取', async t => {
  const { flow, pending } = fixture(t)
  const first = flow.loadDocument(target), second = flow.loadDocument({ ...target, id: 8 }), lots = flow.loadLots(target)
  pending[0].reject(Error('第一单读取失败')); await first
  pending[1].resolve({ ...receipt(1), id: 8 }); await second
  assert.match(flow.readErrors['receipt:7'], /第一单读取失败/)
  assert.equal(flow.readReady['receipt:7'], false); assert.equal(flow.readReady['receipt:8'], true)
  const retry = flow.loadDocument(target)
  flow.cancelDocument(target)
  assert.equal(flow.loading[flow.lotsKey(target)], false)
  pending[2].resolve({ lines: [] }); pending[3].resolve(receipt(1))
  assert.equal(await lots, undefined); assert.equal(await retry, undefined)
  assert.equal(flow.documents['receipt:7'], undefined); assert.equal(flow.documents['receipt:8'].id, 8)
})

test('物料流转同账号权限集合重排保留请求与草稿，角色真正变化立即清理', async t => {
  const { app, flow, pending } = fixture(t)
  flow.draft('dispatch').reason = '已经填写'
  const reading = flow.loadDocument(target)
  app.user = { ...app.user, roles: [...app.user.roles].reverse(), permissions: [...app.user.permissions].reverse() }
  app.server = { ...app.server }
  pending.shift().resolve(receipt(1))
  assert.equal((await reading).id, 7); assert.equal(flow.drafts.dispatch.reason, '已经填写')
  const revoked = flow.loadDocument(target)
  app.user.roles = ['different-role']
  pending.shift().resolve(receipt(2))
  assert.equal(await revoked, undefined); assert.deepEqual(flow.documents, {}); assert.deepEqual(flow.drafts, {})
})

for (const [name, invalidate] of [
  ['证书切换', app => { app.server.fingerprint = 'second' }],
  ['账号退出重登', app => { const user = app.user; app.user = null; app.user = user }],
  ['撤权', app => { app.user.permissions = [] }]
]) test(`物料流转${name}后旧成功和旧失败均不能恢复内容、错误或解除新读取`, async t => {
  const { app, flow, pending } = fixture(t)
  const oldDocument = flow.loadDocument(target), oldOrder = flow.loadOrder(2)
  invalidate(app)
  assert.deepEqual(flow.readReady, {}); assert.deepEqual(flow.readErrors, {})
  app.user = { ...app.user, permissions: ['material_flow.view', 'material_receipt.sign'] }
  const current = flow.loadDocument(target)
  pending[0].resolve(receipt(1)); pending[1].reject(Error('旧会话报错'))
  assert.equal(await oldDocument, undefined); assert.equal(await oldOrder, undefined)
  assert.equal(flow.loading['receipt:7'], true); assert.equal(flow.error, '')
  pending[2].resolve(receipt(2)); assert.equal((await current).version, 2)
})

test('物料流转短暂断线保留同实例正文与草稿，重连必须重读才恢复就绪', async t => {
  const { app, flow, pending } = fixture(t)
  const initial = flow.loadDocument(target); pending.shift().resolve(receipt(1)); await initial
  const displayed = flow.documents['receipt:7']; flow.draft('dispatch').reason = '断线保留'
  const reading = flow.loadDocument(target)
  app.connectionLost = true; app.connectionLost = false
  assert.equal(flow.documents['receipt:7'], displayed); assert.equal(flow.readReady['receipt:7'], false)
  assert.equal(flow.drafts.dispatch.reason, '断线保留')
  pending.shift().resolve(receipt(2)); assert.equal(await reading, undefined)
  assert.equal(flow.readReady['receipt:7'], false)
  const retry = flow.loadDocument(target); pending.shift().resolve(receipt(3)); await retry
  assert.equal(flow.readReady['receipt:7'], true); assert.equal(flow.documents['receipt:7'].version, 3)
})

test('物料流转成功写入的新版本不能被更早的详情或批次结果覆盖', async t => {
  const { flow, pending } = fixture(t)
  const reading = flow.loadDocument(target), lots = flow.loadLots(target)
  globalThis.window.nexora.callApi = async action => action === 'workOrderMaterialFlow' ? order(2) : receipt(2)
  const saved = await flow.execute({ ...target, version: 1, request_id: 'receipt-dialog-save', lines: [{ line_id: 3, quantity: '1' }] })
  assert.equal(saved.version, 2)
  pending[0].resolve(receipt(1)); pending[1].resolve({ lines: [] })
  assert.equal(await reading, undefined); assert.equal(await lots, undefined)
  assert.equal(flow.documents['receipt:7'].version, 2); assert.equal(flow.readReady['receipt:7'], true)
  assert.equal(flow.readReady[flow.lotsKey(target)], false)
})
