import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { VxeUI } from '@vxe-ui/core'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import { parse as parseVue } from '@vue/compiler-sfc'
import postcss from 'postcss'

const viewRoot = new URL('../src/renderer/src/views/workspace/', import.meta.url)

function vueFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? vueFiles(path) : entry.name.endsWith('.vue') ? [path] : []
  })
}

test('公共表格加载真实 vxe 组件并渲染功能区、加载和空状态', async t => {
  // vxe 在浏览器挂载后才生成数据行；这里验证服务端渲染能装载真实组件与公共外壳。
  const server = await createServer({
    configFile: false,
    plugins: [vue()],
    ssr: { noExternal: ['vxe-table'] },
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true },
    appType: 'custom'
  })
  t.after(() => server.close())
  // 只注册语言包并不会启用它；从未安装的语言起步，覆盖冷启动时回退为键名的风险。
  VxeUI.setLanguage('uninstalled-test-language')
  const { default: WorkspaceTable } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceTable.vue')
  await t.test('公共表格启用中文语言包，内置文案不会回退为语言键', () => {
    assert.equal(VxeUI.getLanguage(), 'zh-CN')
    for (const width of [64, 320, 2400]) {
      assert.equal(VxeUI.getI18n('vxe.table.resizeColTip', [width]), `宽：${width} 像素`)
    }
    // 内置空表文案也应使用相同语言，避免只修复单个提示的表面问题。
    assert.equal(VxeUI.getI18n('vxe.table.emptyText'), '暂无数据')
  })
  const columns = [{ key: 'name', title: '名称' }, { key: 'actions', title: '操作' }]
  const slots = {
    actions: () => h('button', '新增'),
    filters: () => h('label', '搜索'),
    'cell-actions': ({ row }) => h('button', `编辑${row.name}`),
    empty: () => '没有匹配的资料'
  }
  // 分页下拉也读取统一主题；测试应用与正式渲染窗口一样装配 Pinia。
  const render = (props, activeSlots = slots) => {
    const app = createSSRApp({
      render: () => h(WorkspaceTable, { title: '资料列表', columns, ...props }, activeSlots)
    }).use(createPinia())
    // Naive UI 在 SSR 中收集样式，不访问浏览器 document。
    setupSsrStyles(app)
    return renderToString(app)
  }

  // 显式固定宽度模式保留原有外层最小宽度；默认铺满模式由 VXE 负责布局。
  const populated = await render({ data: [{ name: '物料 A' }], minTableWidth: 360, stretchColumns: false })
  assert.match(populated, /aria-label="资料列表"/)
  assert.match(populated, /min-width:360px/)
  assert.match(populated, /workspace-vxe-table/)
  // 键盘顺序先条件、后操作，且不再为操作单独保留顶部行。
  assert.ok(populated.indexOf('搜索') < populated.indexOf('新增'))
  assert.match(populated, /workspace-table-toolbar/)
  assert.equal((populated.match(/>新增<\/button>/g) ?? []).length, 1)

  // 页面已有主标题时，仅隐藏卡片标题；操作、说明与表格读屏名称不能丢失。
  const mergedHeading = await render({ showTitle: false, description: '库存查询说明' })
  assert.doesNotMatch(mergedHeading, /<h2/)
  assert.match(mergedHeading, /库存查询说明/)
  assert.match(mergedHeading, /新增/)
  assert.match(mergedHeading, /aria-label="资料列表"/)
  const noHeading = await render({ showTitle: false }, {})
  assert.doesNotMatch(noHeading, /workspace-table-heading/)

  const compactToolbar = await render({ showTitle: false }, {
    ...slots,
    filterActions: () => h('button', '查询')
  })
  assert.doesNotMatch(compactToolbar, /workspace-table-heading/)
  assert.ok(compactToolbar.indexOf('搜索') < compactToolbar.indexOf('查询'))
  assert.ok(compactToolbar.indexOf('查询') < compactToolbar.indexOf('新增'))
  // 无筛选的辅助表格仍能显示原有操作，不能因为合并工具栏丢失按钮。
  const actionsOnly = await render({ showTitle: false }, { actions: slots.actions })
  assert.match(actionsOnly, /workspace-table-heading/)
  assert.match(actionsOnly, /新增/)
  assert.doesNotMatch(actionsOnly, /workspace-table-toolbar/)

  // 页脚总数使用筛选后的总数；空页保留总数并隐藏无效的分页操作。
  const paged = await render({ pagination: { page: 2, pageSize: 20, total: 45 } })
  assert.match(paged, /共 <strong[^>]*>45<\/strong> 条/)
  assert.match(paged, /aria-current="page"/)
  assert.ok(paged.indexOf('workspace-pagination') > paged.indexOf('workspace-vxe-table'))
  assert.ok(paged.indexOf('pagination-total') < paged.indexOf('pagination-controls'))
  // 已有分页列表继续保留首末页边界和加载期间的禁用行为。
  const firstPage = await render({ pagination: { page: 1, pageSize: 20, total: 45 } })
  assert.match(firstPage, /aria-label="上一页"[^>]*disabled/)
  const lastPage = await render({ pagination: { page: 3, pageSize: 20, total: 45 } })
  assert.match(lastPage, /aria-label="下一页"[^>]*disabled/)
  const loadingPage = await render({ loading: true, pagination: { page: 2, pageSize: 20, total: 45 } })
  assert.match(loadingPage, /aria-label="上一页"[^>]*disabled/)
  assert.match(loadingPage, /aria-label="下一页"[^>]*disabled/)
  const zero = await render({ pagination: { page: 1, pageSize: 20, total: 0 } })
  assert.match(zero, /共 <strong[^>]*>0<\/strong> 条/)
  assert.doesNotMatch(zero, /pagination-controls|aria-label="上一页"|aria-label="下一页"|aria-label="第 1 页"/)

  const empty = await render({ data: [] })
  assert.match(empty, /没有匹配的资料/)
  assert.match(empty, /workspace-table-empty-icon/)

  // 查询失败时即使保留了旧数据，也应显示错误和重试入口，不能误报为空结果。
  const failed = await render({ data: [{ name: '旧物料' }], error: '查询失败' }, {
    ...slots,
    errorActions: () => h('button', '重新查询')
  })
  assert.match(failed, /数据加载失败/)
  assert.match(failed, /查询失败/)
  assert.match(failed, /重新查询/)
  assert.doesNotMatch(failed, /没有匹配的资料/)

  const loading = await render({ data: [{ name: '物料 A' }], loading: true })
  assert.match(loading, /正在加载…/)

  const defaultEmpty = await render({ data: [], description: '职务说明' }, {})
  assert.match(defaultEmpty, /职务说明/)
  assert.match(defaultEmpty, /暂无数据/)
})

test('业务页面不再直接创建原生表格或 vxe 表格', () => {
  const component = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  assert.match(component, /<VxeTable\b/)
  assert.match(component, /<VxeColumn\b/)
  // Windows 的 URL pathname 会带有额外的盘符前缀，先转换为本机文件路径。
  for (const path of vueFiles(fileURLToPath(viewRoot))) {
    const source = readFileSync(path, 'utf8')
    assert.doesNotMatch(source, /<table\b|<VxeTable\b/, path)
  }
})

test('新增入口打开弹窗，失败时保留草稿', () => {
  const paths = [
    'catalog/MaterialsView.vue', 'warehouse/OtherInboundsView.vue',
    'purchase/PurchaseOrdersView.vue', 'sales/SalesOrdersView.vue',
    'production/ProductionWorkOrdersView.vue', 'system/UserManagementView.vue'
  ]
  for (const path of paths) {
    const source = readFileSync(new URL(path, viewRoot), 'utf8')
    // 单据新增已迁移到公共弹窗；资料与账号编辑继续使用 Naive 弹窗。
    assert.match(source, /<(?:NModal|WorkspaceDocumentDialog)\b/, path)
    assert.match(source, /@click="(?:edit\(\)|openEditor\(\)|startCreate|showForm = true|createOpen = true|customerOpen = true)"/, path)
    assert.match(source, /submitCreateDialog\(|if \(await saveMaterial/, path)
  }
})

test('公共 vxe 表格匹配工作台明暗主题与单元格高度', () => {
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  assert.match(source, /\.workspace-vxe-table :is\(th, td\) \{[^}]*vertical-align: middle;/)
  // 外层裁切不能成为焦点滚动容器，表体自身继续承担表格滚动。
  assert.match(source, /\.workspace-vxe-table \.vxe-table--viewport-wrapper \{ overflow: clip; \}/)
  // 首列标题和数据使用同一规则，防止只有表头向内缩而内容仍贴边。
  assert.match(source, /:is\(\.vxe-header--column, \.vxe-body--column\):first-child > \.vxe-cell \{ padding-left: 18px; \}/)
  // 边框渐变必须只有一像素高，不能作为整行底色覆盖数据区。
  assert.match(source, /--vxe-ui-table-border-width: 1px;/)
  assert.match(source, /:root\[data-theme='dark'\] \.workspace-vxe-table/)
})

test('表头拖动分割线在明暗主题下常驻可见，悬停突出原生调宽手柄', () => {
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  // 缺少主题变量会让 VXE 的线条透明；同时约束两套主题，避免深色模式回归。
  for (const selector of ['\\.workspace-vxe-table', ":root\\[data-theme='dark'\\] \\.workspace-vxe-table"]) {
    assert.match(source, new RegExp(`${selector} \\{[^}]*--vxe-ui-table-resizable-line-color: #[0-9a-f]{6};`))
  }
  // 线条必须属于真实拖动手柄，不能只给表头加一个无法拖动的装饰边框。
  assert.match(source, /\.workspace-vxe-table \.vxe-header--column > \.vxe-cell--col-resizable::before \{ width: 2px; height: 55%; \}/)
  assert.match(source, /\.workspace-vxe-table \.vxe-header--column > \.vxe-cell--col-resizable:hover::before \{ background-color: var\(--workspace-field-accent\); \}/)
  // 冻结区裁切不能把分割线中心落到相邻普通单元格，保留完整命中范围。
  assert.match(source, /\.vxe-table--fixed-left-wrapper \.vxe-cell--col-resizable \{ right: 0; \}/)
  assert.match(source, /\.vxe-table--fixed-right-wrapper \.vxe-cell--col-resizable \{ left: 0; \}/)
})

test('只隐藏外框及冻结右列交界处的重复线，保留冻结区手柄与普通列边界', () => {
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  const { descriptor } = parseVue(source)
  const hiddenHandleRules = []
  for (const style of descriptor.styles) {
    postcss.parse(style.content).walkRules(rule => {
      if (!rule.selector.includes('vxe-cell--col-resizable')) return
      rule.walkDecls('display', declaration => {
        if (declaration.value === 'none') hiddenHandleRules.push(rule.selector)
      })
    })
  }
  // 使用 VXE 的末列标记，不依赖最后一个 th，避免滚动条占位单元格影响定位。
  // 主表重复线仅在下一列被冻结区隐藏时消失；无溢出、未固定和冻结区自身不匹配。
  // 只隐藏伪元素，不能隐藏手柄元素或影响固定列的拖动命中范围。
  assert.deepEqual(hiddenHandleRules, [
    '.workspace-vxe-table .vxe-table--main-wrapper .vxe-header--column.col--last > .vxe-cell--col-resizable::before',
    '.workspace-vxe-table .vxe-table--main-wrapper .vxe-header--column.fixed--visible:has(+ .vxe-header--column.fixed--hidden.col--fixed) > .vxe-cell--col-resizable::before'
  ])
})


test('公共表格仅保留圆角外框，行分隔线和固定列仍独立绘制', () => {
  const source = readFileSync(new URL('../src/renderer/src/components/workspace/WorkspaceTable.vue', import.meta.url), 'utf8')
  const { descriptor } = parseVue(source)
  const rules = descriptor.styles.flatMap(style => {
    const entries = []
    postcss.parse(style.content).walkRules(rule => entries.push(rule))
    return entries
  })
  const values = selector => Object.fromEntries(rules.filter(rule => rule.selector === selector)
    .flatMap(rule => rule.nodes.filter(node => node.type === 'decl').map(decl => [decl.prop, decl.value])))
  const outer = values('.workspace-vxe-table')
  // 保留公共组件的圆角裁切与完整外框，不通过关闭边框宽度破坏内部行分隔线。
  assert.equal(outer.border, '1px solid #e5edf1')
  assert.equal(outer['border-radius'], '11px')
  assert.equal(outer.overflow, 'hidden')
  assert.equal(outer['--vxe-ui-table-border-width'], '1px')
  assert.equal(values(":root[data-theme='dark'] .workspace-vxe-table")['border-color'], '#2d3e57')
  // 只撤销 VXE 根节点直接绘制的重复外框，不能隐藏主体、冻结区或嵌套表格。
  const suppressedBorders = rules.filter(rule => rule.selector.includes('vxe-table--border-line'))
  assert.equal(suppressedBorders.length, 1)
  assert.equal(suppressedBorders[0].selector, '.workspace-vxe-table > .vxe-table--border-line')
  assert.equal(values(suppressedBorders[0].selector).display, 'none')
  // 默认横线模式只在末行贴外框时撤销末行底线，滚动列表与表内页脚不能受影响。
  const hiddenRowLines = rules.filter(rule => rule.nodes.some(node => node.prop === 'background-image' && node.value === 'none'))
  assert.equal(hiddenRowLines.length, 1)
  assert.equal(hiddenRowLines[0].selector, '.workspace-vxe-table.border--default.not--footer.not--scroll-y .vxe-body--row:last-child > .vxe-body--column')
})
