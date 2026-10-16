import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, createSSRApp, h, markRaw, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import { visibleRouteGroups, workspaceRouteGroups } from '../src/renderer/src/router/workspace-routes.ts'

const allWarehousePermissions = ['inventory.view', 'other_inbound.view', 'other_outbound.view', 'material_flow.view', 'inventory_report.view', 'adjustment.view']
const settle = async () => { await nextTick(); await new Promise(done => setImmediate(done)); await nextTick() }

// 编译并持续挂载真实侧栏，基础按钮只替换绘制，保留页面事件、响应式更新和可访问性属性。
async function fixture(t, permissions = allWarehousePermissions) {
  const filename = resolve('src/renderer/src/components/workspace/WorkspaceSidebar.vue')
  const moduleId = normalizePath(filename) + '.client.ts'
  const source = compileScript(parse(readFileSync(filename, 'utf8'), { filename }).descriptor, {
    id: 'workspace-sidebar-sections', inlineTemplate: true
  }).content
  const server = await createServer({ configFile: false, plugins: [{
    name: 'workspace-sidebar-sections', enforce: 'pre',
    resolveId(id) {
      if (id === moduleId) return id
      if (id.endsWith('/store/app-store')) return '\0sidebar-sections-store'
      if (id.endsWith('/store/settings-store')) return '\0sidebar-sections-settings'
      if (id.endsWith('/AppButton.vue')) return '\0sidebar-sections-button'
      if (id.endsWith('/SidebarAccountCard.vue')) return '\0sidebar-sections-account'
      if (id.startsWith('~icons/')) return '\0sidebar-sections-icon'
    },
    load(id) {
      if (id === moduleId) return source
      if (id === '\0sidebar-sections-store') return `import {ref,shallowRef} from 'vue';
        export const calls=[];export const state={screen:ref('app'),server:ref({isLocal:false}),activeTab:ref('stock'),
          expandedGroupKey:ref('warehouse'),user:ref(null),visibleGroups:shallowRef([]),
          toggleRouteGroup(key){calls.push(['toggle',key]);state.expandedGroupKey.value=state.expandedGroupKey.value===key?null:key},
          navigateToRoute(key){calls.push(['navigate',key]);state.activeTab.value=key}};
        export const useAppStore=()=>state;`
      if (id === '\0sidebar-sections-settings') return 'export const useSettingsStore=()=>({t:source=>source});'
      if (id === '\0sidebar-sections-button') return `import {h} from 'vue';export default {inheritAttrs:false,
        props:['type','variant'],setup:(props,{attrs,slots})=>()=>h('button',{...attrs,type:props.type},slots.default?.())};`
      if (id === '\0sidebar-sections-account') return 'export default {render:()=>null};'
      if (id === '\0sidebar-sections-icon') return `import {h} from 'vue';export default {render:()=>h('svg')};`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Sidebar } = await server.ssrLoadModule(moduleId)
  const { state, calls } = await server.ssrLoadModule('\0sidebar-sections-store')
  // 图标组件模拟共享 store 的最终输出，验证分段不会将管理员选择还原成路由默认图标。
  const icon = key => markRaw({ render: () => h('svg', { 'data-menu-icon': key }) })
  const setPermissions = value => {
    state.visibleGroups.value = visibleRouteGroups(value).map(group => ({ ...group,
      icon: icon(`group:${group.key}`), routes: group.routes.map(route => ({ ...route,
        icon: icon(route.key === 'stock' ? 'custom-stock-truck' : `route:${route.key}`)
      }))
    }))
  }
  setPermissions(permissions)
  // 内存宿主避免浏览器依赖；节点仍由真实 Vue 渲染器挂载与更新，事件直接执行组件绑定。
  const element = tag => markRaw({ tag, children: [], props: {}, text: '', parent: null })
  const root = element('root')
  const renderer = createRenderer({
    createElement: element, createText: text => ({ ...element('#text'), text }), createComment: () => element('#comment'),
    insert(item, parent, anchor) {
      if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, item); item.parent = parent
    },
    remove(item) { if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1); item.parent = null },
    setText(item, text) { item.text = text }, setElementText(item, text) { item.text = text; item.children = [] },
    patchProp(item, key, old, value) { item.props[key] = value }, parentNode: item => item.parent,
    nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] ?? null
  })
  const app = renderer.createApp({ render: () => h(Sidebar) }); app.mount(root)
  t.after(() => app.unmount()); await settle()
  const nodes = (item = root) => [item, ...item.children.flatMap(child => nodes(child))]
  const nodeText = item => [item.text, ...item.children.map(nodeText)].join('')
  const hasClass = (item, name) => String(item.props.class ?? '').split(/\s+/).includes(name)
  const panel = key => nodes().find(item => item.props.id === `route-group-${key}`)
  const buttons = (within = root) => nodes(within).filter(item => item.tag === 'button')
  const button = (label, within = root) => buttons(within).find(item => nodeText(item).trim() === label)
  const press = item => { assert.ok(item, '必须从真实侧栏找到可操作的按钮'); for (const handler of [item.props.onClick].flat()) handler() }
  const titles = (within = root) => nodes(within).filter(item => hasClass(item, 'nav-section-title')).map(item => nodeText(item).trim())
  const render = () => renderToString(createSSRApp({ render: () => h(Sidebar) }))
  return { state, calls, setPermissions, nodes, nodeText, hasClass, panel, buttons, button, press, titles, render }
}

test('真实仓库侧栏按五类分段，基础资料按业务类型分段且标题不增加交互', async t => {
  const f = await fixture(t)
  const warehouse = f.panel('warehouse')
  assert.deepEqual(f.titles(warehouse), ['入库类', '出库类', '生产类', '报表类', '功能类'])
  assert.deepEqual(f.buttons(warehouse).map(item => f.nodeText(item).trim()), [
    '其他入库', '仓库出库', '生产发料', '生产领料', '生产换料', '生产退料',
    '库存总览', '库存预警', '实物批次', '库存台账', '库存报表', '仓库调拨', '库存调整', '库存盘点'
  ])
  const sections = f.nodes(warehouse).filter(item => f.hasClass(item, 'nav-section'))
  assert.equal(sections.length, 5)
  for (const section of sections) {
    const heading = section.children.find(item => item.tag === 'h3')
    assert.ok(heading)
    assert.equal(f.hasClass(section, 'nav-section-grouped'), true)
    assert.equal(section.props.role, 'group')
    assert.equal(section.props['aria-labelledby'], heading.props.id)
    assert.equal(heading.props.tabindex, undefined)
    assert.equal(heading.props.onClick, undefined)
  }
  assert.deepEqual(f.titles(f.panel('catalog')), ['物料类', '往来类', '产品类', '功能类'])
  assert.deepEqual(f.buttons(f.panel('catalog')).map(item => f.nodeText(item).trim()),
    ['物料管理', '物料分类与规格', '单位管理', '供应商管理', '产品与 BOM', '仓库管理'])
  assert.equal(f.hasClass(f.button('工作台首页'), 'nav-home'), true)
  const html = await f.render()
  assert.match(html, /role="group" aria-labelledby="route-section-warehouse-inbound"/)
  assert.match(html, /<h3 id="route-section-warehouse-inbound" class="nav-section-title">入库类<\/h3>/)
})

test('分段入口保留真实导航、高亮、自定义图标及收起时的键盘隔离', async t => {
  const f = await fixture(t)
  const warehouse = f.panel('warehouse')
  const stock = f.button('库存总览', warehouse)
  assert.equal(f.hasClass(stock, 'active'), true)
  assert.equal(stock.props['aria-current'], 'page')
  assert.ok(f.nodes(stock).some(item => item.props['data-menu-icon'] === 'custom-stock-truck'))
  assert.ok(f.nodes(f.button('仓库管理')).some(item => item.props['data-menu-icon'] === 'group:warehouse'))
  f.press(f.button('库存盘点', warehouse)); await settle()
  assert.deepEqual(f.calls.at(-1), ['navigate', 'stocktakes'])
  assert.equal(f.hasClass(f.button('库存总览', warehouse), 'active'), false)
  assert.equal(f.button('库存总览', warehouse).props['aria-current'], undefined)
  assert.equal(f.button('库存盘点', warehouse).props['aria-current'], 'page')
  f.press(f.button('仓库管理')); await settle()
  assert.deepEqual(f.calls.at(-1), ['toggle', 'warehouse'])
  assert.equal(f.panel('warehouse').props['aria-hidden'], true)
  assert.equal(f.panel('warehouse').props.inert, true)
  assert.equal(f.hasClass(f.panel('warehouse'), 'expanded'), false)
  const collapsedHtml = await f.render()
  assert.match(collapsedHtml, /id="route-group-warehouse" class="nav-panel" aria-hidden="true" inert/)
  f.press(f.button('仓库管理')); await settle()
  assert.equal(f.panel('warehouse').props['aria-hidden'], false)
  assert.equal(f.panel('warehouse').props.inert, undefined)
  assert.equal(f.hasClass(f.panel('warehouse'), 'expanded'), true)
  f.press(f.button('工作台首页')); await settle()
  assert.deepEqual(f.calls.at(-1), ['navigate', 'home'])
  assert.equal(f.button('工作台首页').props['aria-current'], 'page')
})

test('已挂载的侧栏随可见权限刷新，隐藏空分段和无权入口且保留系统功能类', async t => {
  const f = await fixture(t)
  for (const [permissions, expectedTitles, expectedRoutes] of [
    [['other_inbound.view'], ['入库类'], ['其他入库']],
    [['other_outbound.view'], ['出库类'], ['仓库出库']],
    [['material_flow.view'], ['生产类'], ['生产发料', '生产领料', '生产换料', '生产退料']],
    [['inventory_report.view'], ['报表类'], ['库存报表']],
    [['adjustment.view'], ['功能类'], ['库存调整']]
  ]) {
    f.setPermissions(permissions); await settle()
    assert.deepEqual(f.titles(f.panel('warehouse')), expectedTitles)
    assert.deepEqual(f.buttons(f.panel('warehouse')).map(item => f.nodeText(item).trim()), expectedRoutes)
  }
  f.setPermissions([]); await settle()
  assert.equal(f.panel('warehouse'), undefined)
  assert.deepEqual(f.titles(), ['功能类'])
  assert.equal(f.button('其他入库'), undefined)
  assert.ok(f.button('工作台首页'))
  assert.deepEqual(f.titles(f.panel('system')), ['功能类'])
  assert.deepEqual(f.buttons(f.panel('system')).map(item => f.nodeText(item).trim()), ['连接与服务'])
  // 旧生产查看账号继续使用独立 BOM 入口；产品类标题不能引入没有授权的合并页面。
  f.setPermissions(['production.view']); await settle()
  assert.deepEqual(f.titles(f.panel('catalog')), ['产品类'])
  assert.deepEqual(f.buttons(f.panel('catalog')).map(item => f.nodeText(item).trim()), ['生产 BOM'])
  assert.equal(f.button('产品与 BOM'), undefined)
})

test('所有业务组均有非交互分类标题，入口不丢失重复且仍按原路由键导航', async t => {
  const permissions = [...new Set(workspaceRouteGroups.flatMap(group => group.routes.map(route => route.permission)).filter(Boolean))]
  const f = await fixture(t, permissions)
  // 一次持续挂载覆盖所有业务组，防止只给仓库或基础资料加分类而遗漏其他菜单。
  for (const group of f.state.visibleGroups.value.filter(group => group.key !== 'home')) {
    const panel = f.panel(group.key)
    assert.ok(f.titles(panel).length > 0, `${group.label}必须有分类标题`)
    assert.equal(f.buttons(panel).length, group.routes.length, `${group.label}的入口不能丢失或重复`)
    for (const section of f.nodes(panel).filter(item => f.hasClass(item, 'nav-section'))) {
      const heading = section.children.find(item => item.tag === 'h3')
      assert.ok(heading, `${group.label}不能遗留没有分类的段落`)
      assert.ok(f.buttons(section).length > 0, '权限过滤后不能显示空分类')
      assert.equal(section.props.role, 'group')
      assert.equal(section.props['aria-labelledby'], heading.props.id)
      assert.equal(heading.props.onClick, undefined)
      assert.equal(heading.props.tabindex, undefined)
    }
    for (const route of group.routes) {
      const marker = route.key === 'stock' ? 'custom-stock-truck' : `route:${route.key}`
      assert.equal(f.nodes(panel).filter(item => item.props['data-menu-icon'] === marker).length, 1)
    }
    const firstRoute = group.routes[0]
    f.press(f.button(firstRoute.label, panel)); await settle()
    assert.deepEqual(f.calls.at(-1), ['navigate', firstRoute.key])
    assert.equal(f.button(firstRoute.label, panel).props['aria-current'], 'page')
  }
  assert.equal(f.panel('home'), undefined)
  assert.equal(f.hasClass(f.button('工作台首页'), 'nav-home'), true)
})
