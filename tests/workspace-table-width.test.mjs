import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 验证真实公共组件交给 VXE 的布局参数，防止页面全部设置列宽时失去自动铺满能力。
test('公共表格默认分配剩余宽度，同时保留窄窗最小列宽及固定列', async t => {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'table-width-fixture', enforce: 'pre',
    transform(code, id) {
      if (id.endsWith('/WorkspaceTable.vue')) return code
        .replace("'vxe-table/es/table'", "'virtual:table-width-table'")
        .replace("'vxe-table/es/column'", "'virtual:table-width-column'")
        .replace("'../../utils/table-column-widths'", "'virtual:table-width-preferences'")
    },
    resolveId(id) {
      if (id === 'virtual:table-width-table') return '\0table-width-table'
      if (id === 'virtual:table-width-column') return '\0table-width-column'
      if (id === 'virtual:table-width-preferences') return '\0table-width-preferences'
    },
    load(id) {
      // 仅替换 VXE 绘制，参数计算和列配置仍由真实 WorkspaceTable 完成。
      if (id === '\0table-width-table') return `import {defineComponent,h} from 'vue';export const captured={};
        export default defineComponent({props:['fit','data','scrollbarConfig','columnConfig','resizableConfig'],setup(p,{slots,attrs}){
          Object.assign(captured,{props:p,attrs});return()=>h('section',slots.default?.())}})`
      if (id === '\0table-width-column') return `import {defineComponent,h} from 'vue';export const captured=[];
        export default defineComponent({props:['field','width','minWidth','fixed','align','headerAlign'],setup(p){
          captured.push({...p});return()=>h('span')}})`
      if (id === '\0table-width-preferences') return `export * from '/src/renderer/src/utils/table-column-widths.ts';
        export const values=new Map();export function tableWidthStorage(){return {getItem:key=>values.get(key)??null,
          setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)}}`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Table } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceTable.vue')
  const { captured: table } = await server.ssrLoadModule('\0table-width-table')
  const { captured: columns } = await server.ssrLoadModule('\0table-width-column')
  const { values } = await server.ssrLoadModule('\0table-width-preferences')
  const render = async props => {
    columns.length = 0
    await renderToString(createSSRApp({ render: () => h(Table, { title: '宽度回归', ...props }) }))
  }

  await t.test('缩小全部配置列宽后，仍启用铺满而非锁死总宽度', async () => {
    const source = [{ key: 'name', title: '名称', width: '120' }, { key: 'unit', title: '单位', width: '60', align: 'center' }]
    const before = structuredClone(source)
    await render({ columns: source, minTableWidth: 580 })
    assert.equal(table.props.fit, true)
    // 调宽由共享组件实时预览，关闭库内数字浮层，用户直接看布局效果。
    assert.equal(table.props.resizableConfig.showDragTip, false)
    assert.deepEqual(columns.map(c => c.width), [undefined, undefined])
    assert.deepEqual(columns.map(c => c.minWidth), ['120', '60'])
    // 铺满模式让 VXE 负责横向滚动，外层不能再撑宽后裁掉明细列。
    assert.equal(table.attrs.style, undefined)
    assert.deepEqual(table.props.scrollbarConfig, { x: { visible: false } })
    assert.equal(columns[1].align, 'center')
    assert.equal(columns[1].headerAlign, 'center')
    assert.deepEqual(source, before)
  })

  await t.test('单据两端固定，中间未指定宽度的列保留最小值供窄窗滚动', async () => {
    await render({ columns: [{ key: 'document', title: '单据号', width: '200' },
      { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作', width: '160' }], minTableWidth: 900 })
    assert.equal(table.props.fit, true)
    assert.deepEqual(columns.map(c => c.fixed), ['left', undefined, 'right'])
    assert.deepEqual(columns.map(c => c.minWidth), ['200', 300, '160'])
    assert.deepEqual(columns.map(c => c.width), [undefined, undefined, undefined])
    assert.equal(table.attrs.style, undefined)
    assert.deepEqual(table.props.scrollbarConfig, { x: { visible: false } })
  })

  await t.test('显式关闭铺满时仍沿用原固定宽度，不改变调用方选择', async () => {
    await render({ stretchColumns: false, columns: [{ key: 'document', title: '单据号', width: '200' },
      { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作', width: '160' }], minTableWidth: 900 })
    assert.deepEqual(columns.map(c => c.width), ['200', 300, '160'])
    assert.deepEqual(columns.map(c => c.minWidth), [undefined, undefined, undefined])
    await render({ stretchColumns: false, columns: [{ key: 'name', title: '名称', width: '200' }], minTableWidth: 580 })
    assert.deepEqual(table.attrs.style, { minWidth: '580px' })
    assert.equal(table.props.scrollbarConfig, undefined)
  })

  await t.test('空表及读取失败也保留铺满配置，失败时不展示旧数据', async () => {
    await render({ columns: [] })
    assert.equal(table.props.fit, true)
    assert.deepEqual(columns, [])
    await render({ columns: [{ key: 'name', title: '名称', width: '120' }], data: [{ name: '旧数据' }], error: '读取失败' })
    assert.equal(table.props.fit, true)
    assert.deepEqual(table.props.data, [])
    assert.equal(columns[0].minWidth, '120')
  })

  await t.test('拖动真实组件事件后保存本机宽度，再次打开恢复且非法事件被拒绝', async () => {
    const source = [{ key: 'name', title: '名称', width: '200' }, { key: 'unit', title: '单位', width: '100' }]
    await render({ columns: source })
    assert.deepEqual(table.props.columnConfig, { resizable: true })
    assert.equal(table.props.resizableConfig.minWidth, 64)
    const resize = table.attrs.onColumnResizableChange
    resize({ column: { field: 'unknown' }, resizeWidth: 150 })
    resize({ column: { field: 'name' }, resizeWidth: Infinity })
    assert.equal(values.size, 0)
    resize({ column: { field: 'name' }, resizeWidth: 180.4 })
    assert.deepEqual(JSON.parse([...values.values()][0]), { version: 1, widths: { name: 180 } })
    await render({ columns: source })
    assert.equal(columns[0].width, 180)
    assert.equal(columns[1].width, undefined)
    assert.equal(columns[1].minWidth, '100')
  })
})
