import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createInventoryTrayAlerts } from '../src/main/inventory-tray-alerts.ts'
import { backendSessionMarker, callBackend, selectBackend } from '../src/main/backend.ts'

const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const event = id => ({ id, status: 'low' })

test('托盘首读建立基线，翻页补读后合并新事件，窗口打开时只更新游标', async () => {
  let marker = 1
  let open = true
  let events = Array.from({ length: 5 }, (_, index) => event(5 - index))
  const notices = []
  const reads = []
  const alerts = createInventoryTrayAlerts({
    sessionMarker: () => marker,
    windowOpen: () => open,
    read: async beforeId => {
      reads.push(beforeId)
      const page = events.filter(item => beforeId === undefined || item.id < beforeId).slice(0, 50)
      return { warehouse_id: null, events: page, next_before_id: page.length === 50 ? page.at(-1).id : null }
    },
    notify: notice => { notices.push(notice) }
  })
  await alerts.poll()
  assert.deepEqual(notices, [])
  events = Array.from({ length: 80 }, (_, index) => event(80 - index))
  open = false
  await alerts.poll()
  assert.deepEqual(reads.slice(1), [undefined, 31])
  assert.deepEqual(notices, [{ outOfStock: 0, low: 75 }])
  await alerts.poll();assert.equal(notices.length, 1)
  events.unshift(event(81));open = true
  await alerts.poll();assert.equal(notices.length, 1)
  events.unshift({ id: 82, status: 'out_of_stock' });open = false
  await alerts.poll()
  assert.deepEqual(notices.at(-1), { outOfStock: 1, low: 0 })
  marker = null
  await alerts.poll()
  marker = 2
  await alerts.poll();assert.equal(notices.length, 2)
})

test('托盘读取失败保留游标，旧账号迟到响应和退出不会发通知', async () => {
  let marker = 1
  let pending = null
  let fail = false
  let events = [event(1)]
  const notices = []
  const alerts = createInventoryTrayAlerts({
    sessionMarker: () => marker,
    windowOpen: () => false,
    read: async () => {
      if (pending) return pending.promise
      if (fail) throw Error('断线')
      return { warehouse_id: null, events, next_before_id: null }
    },
    notify: notice => { notices.push(notice) }
  })
  await alerts.poll()
  events = [event(2), event(1)]
  fail = true
  await alerts.poll();assert.deepEqual(notices, [])
  fail = false
  await alerts.poll();assert.deepEqual(notices, [{ outOfStock: 0, low: 1 }])
  pending = deferred()
  const old = alerts.poll()
  marker = 2
  const next = alerts.poll()
  pending.resolve({ warehouse_id: null, events: [event(3), ...events], next_before_id: null })
  pending = null
  await Promise.all([old, next])
  assert.equal(notices.length, 1)
  const stopping = deferred()
  pending = stopping
  const late = alerts.poll()
  alerts.stop()
  stopping.resolve({ warehouse_id: null, events: [event(4), event(3), ...events], next_before_id: null })
  await late
  assert.equal(notices.length, 1)
})

test('主进程会话代号在重新登录、退出及服务端切换时失效，不暴露令牌', async t => {
  const previousFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = previousFetch; selectBackend(null) })
  selectBackend(null)
  let token = 'first'
  globalThis.fetch = async (url) => {
    if (new URL(url).pathname.endsWith('/login'))
      return new Response(JSON.stringify({ token, user: { id: 1 } }), { status: 200 })
    return new Response(null, { status: 204 })
  }
  assert.equal(backendSessionMarker(), null)
  await callBackend('login', {})
  const first = backendSessionMarker()
  assert.equal(typeof first, 'number')
  await callBackend('login', {})
  assert.notEqual(backendSessionMarker(), first)
  token = 'second'
  await callBackend('login', {})
  assert.notEqual(backendSessionMarker(), first)
  await callBackend('logout', undefined)
  assert.equal(backendSessionMarker(), null)
  await callBackend('login', {})
  selectBackend({ host: '127.0.0.1', port: 8000, instanceId: 'new', certificate: 'cert' })
  assert.equal(backendSessionMarker(), null)
})

test('旧请求的 401 不清除新登录会话', async t => {
  const previousFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = previousFetch; selectBackend(null) })
  selectBackend(null)
  const delayed = deferred()
  let token = 'first'
  globalThis.fetch = async url => {
    const path = new URL(url).pathname
    if (path.endsWith('/login'))
      return new Response(JSON.stringify({ token, user: { id: 1 } }), { status: 200 })
    return delayed.promise
  }
  await callBackend('login', {})
  const old = callBackend('inventoryWarningEvents', undefined)
  token = 'second'
  await callBackend('login', {})
  const current = backendSessionMarker()
  delayed.resolve(new Response(JSON.stringify({ detail: '会话失效' }), { status: 401 }))
  await assert.rejects(old, /会话失效/)
  assert.equal(backendSessionMarker(), current)
})
