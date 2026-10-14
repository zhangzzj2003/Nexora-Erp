import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 只替换外围展示和接口，实际页面的请求代次、草稿赋值及关闭监听参与回归。
const storeSource = `import {defineStore} from 'pinia';import {ref} from 'vue';
export const usePiniaAppStore=defineStore('dialog-preparation-view',()=>({
 materialUnits:ref([]),warehouses:ref([]),busy:ref(false),connectionLost:ref(false),
 materials:ref([]),customers:ref([]),salesOrders:ref([]),salesForm:ref({lines:[]}),error:ref(''),notice:ref(''),
 loadSalesOrderContract:async id=>window.nexora.callApi('salesOrderContract',{id}),
 user:ref({id:1,permissions:['catalog.manage','warehouse.manage']}),server:ref({id:'local',fingerprint:'certificate'}),
 can:()=>true,saveMaterialUnit:async()=>false,saveWarehouse:async()=>false,localTime:value=>value
}));`
async function fixture(t, name, directory = 'catalog') {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'dialog-view-preparation-fixture', enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.includes('/src/renderer/')) return
      if (id.endsWith('/store/app-store')) return '\0prepare-store'
      if (id.endsWith('.vue') && !id.includes('/views/workspace/catalog/')) return '\0prepare-empty'
    },
    load(id) {
      if (id === '\0prepare-store') return storeSource
      if (id === '\0prepare-empty') return `export default {render:()=>null}`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore } = await server.ssrLoadModule('\0prepare-store')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const { default: View } = await server.ssrLoadModule(`/src/renderer/src/views/workspace/${directory}/${name}.vue`)
  const calls = []
  const previous = globalThis.window
  globalThis.window = { nexora: { callApi: (method, payload) => new Promise((resolve, reject) => calls.push({ method, payload, resolve, reject })) } }
  t.after(() => { globalThis.window = previous })
  const exercise = async action => {
    const Open = { ...View, async setup(props, context) {
      const page = View.setup(props, context)
      await action(page)
      return page
    } }
    await renderToString(createSSRApp({ render: () => h(Open) }).use(pinia))
  }
  return { store, calls, exercise }
}

test('仓库修订先记录打开意图，取消后旧响应不能覆盖后一次修订或重开窗口', async t => {
  const { calls, exercise } = await fixture(t, 'WarehousesView')
  await exercise(async page => {
    const first = page.edit({ id: 1 })
    assert.equal(page.showForm.value, true)
    assert.equal(page.detailLoading.value, true)
    page.showForm.value = false
    const second = page.edit({ id: 2 })
    assert.equal(page.detailLoading.value, true)
    calls[0].resolve({ id: 1, code: 'OLD', name: '过期仓库', version: 1 })
    await first
    assert.equal(page.detailLoading.value, true, '旧请求结束不能解除新窗口屏障')
    assert.notEqual(page.form.name, '过期仓库')
    calls[1].resolve({ id: 2, code: 'NEW', name: '当前仓库', version: 3 })
    await second
    assert.equal(page.showForm.value, true)
    assert.equal(page.detailLoading.value, false)
    assert.equal(page.form.name, '当前仓库')
    page.showForm.value = false
    const cancelled = page.edit({ id: 3 })
    page.showForm.value = false
    calls[2].resolve({ id: 3, code: 'LATE', name: '已取消', version: 1 })
    await cancelled
    assert.equal(page.showForm.value, false)
    assert.equal(page.form.name, '当前仓库')
  })
})

test('单位变更记录等待可取消，失败结束加载且不把空记录作为成功详情', async t => {
  const { calls, exercise } = await fixture(t, 'UnitsView')
  await exercise(async page => {
    const cancelled = page.history({ id: 1, name: '个' })
    assert.equal(page.auditOpen.value, true)
    assert.equal(page.loading.value, true)
    page.auditOpen.value = false
    calls[0].resolve([{ id: 77 }])
    await cancelled
    assert.equal(page.auditOpen.value, false)
    assert.deepEqual(page.auditRows.value, [])
    assert.equal(page.loading.value, false)
    const failed = page.history({ id: 2, name: '箱' })
    calls[1].reject(new Error('读取变更失败'))
    await failed
    assert.equal(page.loading.value, false)
    assert.match(page.detailError.value, /读取变更失败/)
    assert.deepEqual(page.auditRows.value, [])
  })
})

test('资料读取使用稳定会话签名，同账号快照刷新保留结果，切换账号丢弃迟到响应', async t => {
  const { store, calls, exercise } = await fixture(t, 'WarehousesView')
  await exercise(async page => {
    const refresh = page.edit({ id: 1 })
    store.user = { ...store.user }
    calls[0].resolve({ id: 1, code: 'SAME', name: '同一会话', version: 2 })
    await refresh
    assert.equal(page.form.name, '同一会话')
    page.showForm.value = false
    const changed = page.edit({ id: 2 })
    store.user = { ...store.user, id: 2 }
    calls[1].resolve({ id: 2, code: 'OTHER', name: '旧账号结果', version: 1 })
    await changed
    assert.equal(page.showForm.value, false)
    assert.equal(page.form.name, '同一会话')
  })
})

// 回到同一订单也属于新打开请求，旧合同结果绝不能先解除新窗口的等待状态。
test('销售合同取消后重开同一订单，旧响应不覆盖新正文或提前结束等待', async t => {
  const { calls, exercise } = await fixture(t, 'SalesOrdersView', 'sales')
  await exercise(async page => {
    const order = { id: 1 }
    const first = page.openContract(order)
    assert.equal(page.contractOpen.value, true)
    page.contractOpen.value = false
    const second = page.openContract(order)
    calls[0].resolve({ version: 1, current: { body: '过期合同' } })
    await first
    assert.equal(page.contractLoading.value, true)
    assert.equal(page.contract.value, null)
    calls[1].resolve({ version: 2, current: { body: '最新合同' } })
    await second
    assert.equal(page.contractLoading.value, false)
    assert.equal(page.contractBody.value, '最新合同')
    assert.equal(page.contract.value.version, 2)
  })
})
