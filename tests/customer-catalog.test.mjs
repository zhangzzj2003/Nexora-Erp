import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h, ref, toRaw } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createMemoryHistory } from 'vue-router'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createWorkspaceRouter, installWorkspaceAccessGuard } from '../src/renderer/src/router/index.ts'
import { workspaceRoutes, visibleRouteGroups } from '../src/renderer/src/router/workspace-routes.ts'
import { createSalesActions } from '../src/renderer/src/store/modules/sales-actions.ts'
import { submitCreateDialog } from '../src/renderer/src/utils/create-dialog.ts'
import { callBackend } from '../src/main/backend.ts'
import { parseCustomerCsv } from '../src/renderer/src/views/workspace/catalog/customer-import.ts'

test('客户资料归属基础资料，直接访问及撤销权限遵循销售查看权限', async () => {
  const group = visibleRouteGroups(['sales.view']).find(group => group.key === 'catalog')
  assert.deepEqual(group.routes.map(route => route.key), ['customers'])
  assert.equal(visibleRouteGroups(['customer.manage']).some(group => group.key === 'catalog'), false)
  const component = { render: () => null }
  const router = createWorkspaceRouter(createMemoryHistory(), Object.fromEntries(workspaceRoutes.map(route => [route.key, component])))
  let permissions = ['sales.view']
  installWorkspaceAccessGuard(router, () => permissions)
  await router.push('/workspace/customers')
  assert.equal(router.currentRoute.value.name, 'customers')
  await router.push('/workspace/sales-orders')
  permissions = []
  await router.push('/workspace/customers')
  assert.equal(router.currentRoute.value.name, 'home')
})

test('独立客户页显示名单并约束新增操作，销售订单页不再包含客户列表', async t => {
  // 使用真实 Pinia 响应式状态和页面模板，仅替换表格内部渲染与数据来源。
  const server = await createServer({ configFile: false, plugins: [{
    name: 'customer-fixtures', enforce: 'pre',
    resolveId(id, importer) {
      if (!importer?.includes('/views/workspace/')) return
      if (id.endsWith('/store/app-store')) return '\0customer-store'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0customer-table'
    },
    load(id) {
      if (id === '\0customer-store') return `
        import {defineStore,storeToRefs} from 'pinia'
        export const permissions = new Set(['sales.view'])
        export const usePiniaAppStore = defineStore('customer-test', {
          state:()=>({busy:false,connectionLost:false,user:{id:1,permissions:['sales.view']},error:'',notice:'',customers:[{id:1,name:'测试客户甲'}],customerForm:{name:''},salesOrders:[],salesForm:{customer_id:0,reference:'',lines:[]},materials:[]}),
          actions:{can(p){return permissions.has(p)},createCustomer(){},navigateToRoute(){},localTime(v){return v}}
        })
        export const useAppStore = ()=>{const s=usePiniaAppStore();return {...s,...storeToRefs(s)}}
      `
      if (id === '\0customer-table') return `
        import {defineComponent,h} from 'vue'
        export default defineComponent({props:['data','title'],setup(p,{slots}){
          return ()=>h('section',{'aria-label':p.title},[slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...p.data.map(row=>h('p',row.name)),p.data.length?null:slots.empty?.()])
        }})
      `
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore, permissions } = await server.ssrLoadModule('\0customer-store')
  const pinia = createPinia()
  const store = usePiniaAppStore(pinia)
  const render = async file => {
    const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/' + file)
    return renderToString(createSSRApp({ render: () => h(View) }).use(pinia))
  }
  const customers = 'catalog/CustomersView.vue'
  const readonlyHtml = await render(customers)
  assert.match(readonlyHtml, /测试客户甲/)
  assert.doesNotMatch(readonlyHtml, /新增客户/)
  permissions.add('customer.manage')
  assert.match(await render(customers), /新增客户/)
  assert.match(await render(customers), /导入客户 CSV/)
  store.connectionLost = true
  assert.match(await render(customers), /<button[^>]*disabled[^>]*>[\s\S]*?新增客户[\s\S]*?<\/button>/)
  store.customers = []
  assert.match(await render(customers), /暂无客户，请先新增/)
  const sales = await render('sales/SalesOrdersView.vue')
  assert.match(sales, /aria-label="销售订单"/)
  assert.doesNotMatch(sales, /aria-label="客户资料"|搜索客户|新增客户/)
})

test('客户新增失败保留草稿和弹窗，成功刷新共享名单且不清空订单草稿', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  let fails = true
  const customerForm = ref({ name: '测试客户' })
  const salesForm = ref({ customer_id: 0, reference: '保留的参考单号', lines: [{ material_id: 8, quantity: '2', unit_price: '3' }] })
  const draft = structuredClone(toRaw(salesForm.value))
  const customers = ref([])
  const state = { busy: ref(false), error: ref(''), notice: ref('') }
  globalThis.window = { nexora: { async callApi(action, payload) {
    assert.equal(action, 'createCustomer')
    assert.deepEqual(payload, { name: '测试客户' })
    if (fails) throw new Error('客户名称已存在')
    return { id: 9, name: payload.name }
  } } }
  const actions = createSalesActions({ customerForm, salesForm }, async (action, success) => {
    state.error.value = ''
    try {
      await action()
      // 模拟统一 perform 成功后的快照刷新，订单与客户页读取同一份名单。
      customers.value = [{ id: 9, name: '测试客户' }]
      state.notice.value = success
    } catch (error) { state.error.value = error.message }
  })
  const open = ref(true)
  await submitCreateDialog(actions.createCustomer, state, open)
  assert.equal(open.value, true)
  assert.equal(customerForm.value.name, '测试客户')
  assert.deepEqual(salesForm.value, draft)
  fails = false
  await submitCreateDialog(actions.createCustomer, state, open)
  assert.equal(open.value, false)
  assert.equal(customerForm.value.name, '')
  assert.equal(customers.value[0].id, 9)
  assert.deepEqual(salesForm.value, draft)
})

test('销售订单创建仅传递已校验的保修条款和订单字段', async t => {
  const originalWindow=globalThis.window,originalFetch=globalThis.fetch
  t.after(()=>{globalThis.window=originalWindow;globalThis.fetch=originalFetch})
  const sent=[]
  globalThis.fetch=async(url,options)=>{
    if(new URL(url).pathname.endsWith('/login'))
      return new Response(JSON.stringify({token:'test',user:{id:1}}),{status:200})
    sent.push([new URL(url).pathname,JSON.parse(options.body)])
    return new Response(JSON.stringify({id:1}),{status:200})
  }
  const line={material_id:8,quantity:'2',unit_price:'3',warranty_days:365,warranty_basis:' 合同 W-365 ',hidden:'不可发送'}
  await callBackend('login',{})
  await callBackend('createSalesOrder',{customer_id:2,reference:'SO-1',lines:[line],hidden:'不可发送'})
  assert.deepEqual(sent[0],[
    '/api/v1/sales-orders',{customer_id:2,reference:'SO-1',lines:[{
      material_id:8,quantity:'2',unit_price:'3',warranty_days:365,warranty_basis:'合同 W-365'
    }]}
  ])
  await assert.rejects(callBackend('createSalesOrder',{customer_id:2,reference:'SO-1',lines:[{...line,warranty_days:30.5}]}),/保修天数无效/)
  await assert.rejects(callBackend('createSalesOrder',{customer_id:2,reference:'SO-1',lines:[{...line,warranty_days:null}]}),/保修依据无效/)
  assert.equal(sent.length,1)
})

test('重复客户候选只经固定 IPC 路径查询并校验名称', async t => {
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const requests = []
  globalThis.fetch = async (url, config) => {
    requests.push({ path: new URL(url).pathname, method: config.method,
      body: JSON.parse(config.body) })
    return new Response(new URL(url).pathname.endsWith('/login')
      ? JSON.stringify({ token: 'test', user: { id: 1 } }) : '[]', { status: 200 })
  }
  await callBackend('login', {})
  requests.length = 0
  await callBackend('customerDuplicateCandidates', { name: ' 客户甲 ', path: '/api/v1/users' })
  assert.deepEqual(requests, [{ path: '/api/v1/customers/duplicate-candidates',
    method: 'POST', body: { name: '客户甲' } }])
  for (const name of ['', '   ', 'x'.repeat(121), 42]) {
    await assert.rejects(callBackend('customerDuplicateCandidates', { name }), /客户名称无效/)
  }
  assert.equal(requests.length, 1)
})

test('客户 CSV 导入只读取单列，支持带逗号和引号的名称', () => {
  assert.deepEqual(parseCustomerCsv('\uFEFF客户名称\r\n客户甲\r\n"上海,华星"\r\n"简称""甲"""\r\n'),
    ['客户甲', '上海,华星', '简称"甲"'])
  assert.deepEqual(parseCustomerCsv('name\n客户乙\n'), ['客户乙'])
  for (const csv of ['客户,电话\n甲,123', 'name\n', 'name\n甲,乙',
    'name\n"未闭合', 'name\n甲\n\n乙', 'name\n甲\n'.repeat(101)]) {
    assert.throws(() => parseCustomerCsv(csv))
  }
})

test('客户批量预检和导入只转发名单、依据及显式相似确认', async t => {
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  const requests = []
  globalThis.fetch = async (url, config) => {
    const path = new URL(url).pathname
    const body = config.body ? JSON.parse(config.body) : null
    requests.push({ path, method: config.method, body })
    const output = path.endsWith('/login') ? { token: 'test', user: { id: 1 } }
      : path.endsWith('/import-preview') ? { rows: body.names.map((name, index) => ({
        row: index + 1, name, candidates: [], batch_candidates: [],
        can_import: true, requires_confirmation: false
      })), can_import: true, requires_confirmation: false }
      : { batch_reference: '0123456789abcdef', created: body.names.map((name, index) => ({
        id: index + 1, name, owner_id: 1, version: 1
      })) }
    return new Response(JSON.stringify(output), { status: 200 })
  }
  await callBackend('login', {})
  requests.length = 0
  await callBackend('customerImportPreview', { names: [' 客户甲 '], path: '/users' })
  await callBackend('importCustomers', { names: [' 客户甲 '], reason: ' 来源核对 ',
    allow_similar: true, owner_id: 99 })
  assert.deepEqual(requests, [
    { path: '/api/v1/customers/import-preview', method: 'POST', body: { names: ['客户甲'] } },
    { path: '/api/v1/customers/import', method: 'POST',
      body: { names: ['客户甲'], reason: '来源核对', allow_similar: true } }
  ])
  for (const names of [[], [''], ['x'.repeat(121)], Array(101).fill('甲'), [23]]) {
    await assert.rejects(callBackend('customerImportPreview', { names }), /客户导入名单无效/)
  }
  await assert.rejects(callBackend('importCustomers', {
    names: ['甲'], reason: '', allow_similar: false }), /依据或相似名称确认无效/)
  assert.equal(requests.length, 2)
})

test('客户导入响应不匹配名单时拒绝展示或确认成功', async t => {
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = async url => new Response(JSON.stringify(new URL(url).pathname.endsWith('/login')
    ? { token: 'test', user: { id: 1 } } : { rows: [], can_import: true,
      requires_confirmation: false, batch_reference: '0123456789abcdef', created: [] }), { status: 200 })
  await callBackend('login', {})
  await assert.rejects(callBackend('customerImportPreview', { names: ['客户甲'] }), /预检响应格式无效/)
  await assert.rejects(callBackend('importCustomers', { names: ['客户甲'],
    reason: '核对资料', allow_similar: false }), /导入结果格式无效/)
})

test('客户批量写操作经 Pinia 刷新，提交成功但刷新失败时不引导重复导入', async t => {
  const original = globalThis.window
  t.after(() => { globalThis.window = original })
  let calls = 0
  let failWrite = false
  globalThis.window = { nexora: { async callApi(action, payload) {
    calls++
    assert.equal(action, 'importCustomers')
    assert.deepEqual(payload, { names: ['客户甲'], reason: '核对资料', allow_similar: true })
    if (failWrite) throw Error('导入冲突')
    return { batch_reference: 'abc123', created: [{ id: 8, name: '客户甲' }] }
  } } }
  const state = { user: ref({ id: 1 }), notice: ref(''), error: ref('') }
  const perform = async (action, success) => {
    state.error.value = ''
    try { await action(); throw Error('名单刷新失败') }
    catch (cause) { state.error.value = cause.message }
    if (!state.error.value) state.notice.value = success
  }
  const actions = createSalesActions(state, perform)
  const result = await actions.importCustomerNames(['客户甲'], '核对资料', true)
  assert.equal(result.created[0].id, 8)
  assert.match(state.notice.value, /已导入 1 位客户.*名单刷新失败/)
  assert.equal(state.error.value, '')
  failWrite = true
  assert.equal(await actions.importCustomerNames(['客户甲'], '核对资料', true), null)
  assert.equal(state.error.value, '导入冲突')
  assert.equal(calls, 2)
})
