import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vue from '@vitejs/plugin-vue'
import { createServer } from 'vite'

// 只替换分页绘制，验证公共组件真实绑定与事件，避免查询接口在迁移后失效。
test('公共 Naive UI 分页保持受控页码、条数重置和失败路径保护', async t => {
  const server = await createServer({ configFile: false, plugins: [{
    name: 'pagination-fixture', enforce: 'pre',
    transform(code, id) { if (id.endsWith('/WorkspacePagination.vue')) return code.replace("'naive-ui'", "'virtual:pagination'") },
    resolveId(id) { if (id === 'virtual:pagination') return '\0pagination' },
    load(id) { if (id === '\0pagination') return `import {defineComponent,h} from 'vue';export const captured={};
      export const NPagination=defineComponent({props:['page','pageSize','pageCount','pageSlot','pageSizes','showSizePicker','disabled','label'],
        setup(p,{attrs,slots}){Object.assign(captured,{props:p,attrs});return()=>h('div',[slots.prev?.(),slots.next?.()])}})` }
  }, vue()], server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true, include: [] }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Pagination } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspacePagination.vue')
  const { captured } = await server.ssrLoadModule('\0pagination')
  let calls
  const render = async props => {
    calls = []
    return renderToString(createSSRApp({ render: () => h(Pagination, { page: 2, pageSize: 20, total: 45, ...props,
      onChange: (page, size) => calls.push([page, size]) }) }))
  }
  await render()
  assert.equal(captured.props.page, 2)
  assert.equal(captured.props.pageSize, 20)
  assert.equal(captured.props.pageCount, 3)
  assert.equal(captured.props.showSizePicker, '')
  assert.deepEqual(captured.props.pageSizes, [10, 20, 30, 40, 50, 100])
  captured.attrs['onUpdate:page'](3)
  captured.attrs['onUpdate:pageSize'](10)
  assert.deepEqual(calls, [[3, 20], [1, 10]])
  for (const page of [0, 4, 1.5, NaN, Infinity, 2]) captured.attrs['onUpdate:page'](page)
  for (const size of [0, -1, 15, NaN, Infinity, 20]) captured.attrs['onUpdate:pageSize'](size)
  assert.equal(calls.length, 2)
  const label = captured.props.label({ type: 'page', node: 2, active: true })
  assert.equal(label.type, 'button')
  assert.equal(label.props.type, 'button')
  assert.equal(label.props['aria-current'], 'page')
  assert.equal(label.props['aria-label'], '第 2 页')
  await render({ disabled: true })
  captured.attrs['onUpdate:page'](3)
  captured.attrs['onUpdate:pageSize'](10)
  assert.deepEqual(calls, [])
  assert.equal(captured.props.label({ type: 'page', node: 2, active: true }).props.disabled, true)
  const single = await render({ page: 1, total: 5 })
  assert.equal(captured.props.pageCount, 1)
  assert.match(single, /aria-label="上一页"[^>]*disabled/)
  assert.match(single, /aria-label="下一页"[^>]*disabled/)
  const empty = await render({ page: 1, total: 0 })
  assert.match(empty, /共 <strong[^>]*>0<\/strong> 条/)
  assert.doesNotMatch(empty, /aria-label="上一页"|aria-label="下一页"/)
})
