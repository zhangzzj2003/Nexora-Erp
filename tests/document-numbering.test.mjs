import assert from 'node:assert/strict'
import { test, before, after } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import Icons from 'unplugin-icons/vite'
import { documentNumberingBody, validateDocumentNumbering, validateDocumentNumbers, documentLabel, documentSearch } from '../src/shared/document-numbering.ts'
import { numberingDate } from '../src/renderer/src/utils/document-numbering-preview.ts'
import { createConnectionActions } from '../src/renderer/src/store/connection-actions.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'

// 从真实服务端时间测试预览与边界校验，不使用客户端当天日期生成编号。
const config = { configured: false, style: null, timezone_mode: 'server', timezone: null,
  version: 0, locked: false, configured_by: null, configured_at: null,
  server_time: '2026-10-07T00:01:00+08:00', business_time: '2026-10-07T00:01:00+08:00',
  business_date: '20261007', timezones: ['Asia/Shanghai', 'America/New_York', 'UTC'], backfilled_count: 0, undated_count: 0 }
const input = { style: 'pinyin', timezone_mode: 'server', timezone: null, version: 0 }

test('预览区分服务端本机、UTC 和指定时区，语言切换不修改单号', () => {
  validateDocumentNumbering(config)
  assert.equal(numberingDate(config, input), '20261007')
  assert.equal(numberingDate(config, { ...input, timezone_mode: 'utc' }), '20261006')
  assert.equal(numberingDate(config, { ...input, timezone_mode: 'specified', timezone: 'America/New_York' }), '20261006')
  assert.equal(numberingDate(config, { ...input, timezone_mode: 'specified', timezone: 'Invalid' }), '')
  const row = { id: 5, document_no: 'CGDD-20261007-1000000' }
  assert.equal(documentLabel(row), row.document_no)
  assert.match(documentSearch({ ...row, purchase_request_document_no: 'CGSQ-20261006-000001' }), /CGSQ/)
})

test('受限桥接拒绝非法配置与编号响应，过滤额外参数', () => {
  assert.deepEqual(documentNumberingBody({ ...input, locked: false, extra: 'ignored' }), input)
  for (const bad of [{ style: 'auto' }, { version: -1 }, { version: true }, { timezone: 'UTC' }])
    assert.throws(() => documentNumberingBody({ ...input, ...bad }))
  for (const bad of [{ locked: true }, { version: '1' }, { configured_by: 'admin' }, { backfilled_count: -1 }])
    assert.throws(() => validateDocumentNumbering({ ...config, ...bad }))
  validateDocumentNumbers({ document_no: null, rows: [{ source_document_no: 'PO-20261007-000001' }] })
  for (const number of ['#1', '', 1, 'PO-20261007-1'])
    assert.throws(() => validateDocumentNumbers({ rows: [{ document_no: number }] }))
})

test('首次登录及恢复会话强制管理员设置，普通用户仍查询，切换实例清空规则', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  for (const restore of [false, true]) for (const roles of [['admin'], ['viewer']]) {
    let refreshes = 0
    globalThis.window = { nexora: {
      startup: async () => ({ status: 'connected', server: { id: 'server-a' } }),
      callApi: async action => action === 'documentNumbering' ? config : { id: 1, roles, permissions: [] },
      recentServers: async () => [], hostStatus: async () => ({}), disconnect: async () => {}
    } }
    const state = createAppState(); state.screen.value = 'login'
    const actions = createConnectionActions(state, async () => { refreshes++ })
    if (restore) await actions.checkConnection(); else await actions.authenticate()
    assert.equal(state.screen.value, roles[0] === 'admin' ? 'numbering' : 'app')
    assert.equal(refreshes, roles[0] === 'admin' ? 0 : 1)
    await actions.switchServer()
    assert.equal(state.documentNumbering.value, null)
  }
})

let server, SettingsPage, useStore, useSettings
before(async () => {
  // SSR 仅替换浏览器地址历史，设置表单、Naive UI 和 Pinia 均执行实际组件。
  server = await createServer({ configFile: false, plugins: [vue(), Icons({ compiler: 'vue3' }), {
    name: 'numbering-memory-router', load(id) {
      if (id.endsWith('/router/browser-router.ts')) return "import { createRouter, createMemoryHistory } from 'vue-router'; export const workspaceRouter = createRouter({history:createMemoryHistory(),routes:[]})"
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: SettingsPage } = await server.ssrLoadModule('/src/renderer/src/components/workspace/DocumentNumberingSettings.vue'))
  ;({ usePiniaAppStore: useStore } = await server.ssrLoadModule('/src/renderer/src/store/app-store.ts'))
  ;({ useSettingsStore: useSettings } = await server.ssrLoadModule('/src/renderer/src/store/settings-store.ts'))
})
after(() => server?.close())

test('真实设置页展示双风格示例、中英文、锁定只读和断网禁用', async () => {
  const pinia = createPinia(), store = useStore(pinia), settings = useSettings(pinia)
  store.user = { id: 1, roles: ['admin'], permissions: [] }; store.documentNumbering = config
  async function render() {
    const app = createSSRApp({ render: () => h(SettingsPage, { initial: true }) }).use(pinia)
    setupSsrStyles(app); return renderToString(app)
  }
  const chinese = await render()
  assert.match(chinese, /QTRK-20261007-000001/); assert.match(chinese, /OIN-20261007-000001/)
  assert.match(chinese, /保存编号规则/); assert.match(chinese, /切换服务端/)
  settings.setLocale('en-US')
  assert.match(await render(), /Save numbering policy/)
  store.connectionLost = true
  assert.match(await render(), /type="submit"[^>]*disabled/)
  store.documentNumbering = { ...config, configured: true, style: 'english', locked: true, version: 1 }
  const locked = await render()
  assert.match(locked, /policy are locked/); assert.doesNotMatch(locked, /type="submit"/)
})


test('另一管理员完成设置后，等待管理员读取已锁定规则即可离开首次引导', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  const account = { id: 1, roles: ['admin'], permissions: [] }
  const confirmed = { ...config, configured: true, locked: true, style: 'english', version: 1 }
  // 直接执行真实 Pinia 操作，覆盖后台轮询和保存冲突后的同一重读入口。
  globalThis.window = { nexora: { callApi: async action =>
    action === 'me' ? account : action === 'documentNumbering' ? confirmed : [] } }
  const store = useStore(createPinia())
  store.user = account; store.screen = 'numbering'; store.documentNumbering = config
  await store.loadDocumentNumbering()
  assert.equal(store.screen, 'app')
  assert.equal(store.documentNumbering.style, 'english')
  assert.equal(store.documentNumbering.locked, true)
})


test('切换服务端后到达的旧规则响应不能污染新实例', async t => {
  const previous = globalThis.window
  t.after(() => { globalThis.window = previous })
  let resolveRead
  const pending = new Promise(resolve => { resolveRead = resolve })
  globalThis.window = { nexora: { callApi: async () => pending } }
  const store = useStore(createPinia())
  store.user = { id: 1, roles: ['admin'], permissions: [] }
  store.server = { id: 'before' }; store.screen = 'numbering'; store.documentNumbering = config
  const loading = store.loadDocumentNumbering()
  // 模拟请求在旧服务端发出，用户切换完成后响应才到达。
  store.server = { id: 'after' }; store.documentNumbering = null; store.screen = 'login'
  resolveRead({ ...config, configured: true, style: 'english', locked: true, version: 1 })
  await loading
  assert.equal(store.documentNumbering, null)
  assert.equal(store.screen, 'login')
})
