import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { updateWorkspaceSearchFilter } from '../src/renderer/src/utils/workspace-search-filters.ts'

// 校验组件事件边界：数字和字符串 ID 不互换，失效选项及禁用回调不能改写模型。
test('公共筛选更新不修改原对象，拦截禁用、未知键、非法日期和失效选项', () => {
  const model = { person: null, from: '', other: '保留字段' }
  const select = { kind: 'select', key: 'person', label: '处理人', options: [{ value: null, label: '全部' }, { value: 1, label: '甲' }, { value: 2, label: '乙', disabled: true }] }
  assert.deepEqual(updateWorkspaceSearchFilter(model, select, 1), { ...model, person: 1 })
  for (const value of ['1', 2, 999]) assert.equal(updateWorkspaceSearchFilter(model, select, value), undefined)
  assert.equal(updateWorkspaceSearchFilter(model, select, 1, true), undefined)
  assert.equal(updateWorkspaceSearchFilter(model, { ...select, key: 'unknown' }, 1), undefined)
  const date = { kind: 'date', key: 'from', label: '开始日期' }
  assert.deepEqual(updateWorkspaceSearchFilter(model, date, '2024-02-29'), { ...model, from: '2024-02-29' })
  assert.deepEqual(updateWorkspaceSearchFilter(model, date, ''), model)
  for (const value of ['2026-02-29', '2026-1-1', 123, null]) assert.equal(updateWorkspaceSearchFilter(model, date, value), undefined)
  assert.deepEqual(model, { person: null, from: '', other: '保留字段' })
})

// 使用真实 Vue/Naive 控件，验证页面可只接搜索，以及事件、读屏标签和禁用保护。
test('公共组件按配置展示搜索、筛选、日期与提示，并发送受控更新和重置事件', async t => {
  const server = await createServer({ configFile: false, plugins: [vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Component } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceSearchFilters.vue')
  const events = [], filters = { person: null, from: '', to: '' }
  const fields = [{ kind: 'select', key: 'person', label: '处理人', options: [{ value: null, label: '全部处理人' }, { value: 1, label: '甲' }] },
    { kind: 'date', key: 'from', label: '开始日期', maxKey: 'to' }, { kind: 'date', key: 'to', label: '结束日期', minKey: 'from' }]
  let vnode
  const render = async overrides => {
    vnode = h(Component, { query: '电阻', filters, fields, searchLabel: '搜索入库单', issue: '日期范围错误',
      'onUpdate:query': value => events.push(['query', value]), 'onUpdate:filters': value => events.push(['filters', value]), onReset: () => events.push(['reset']), ...overrides })
    const app = createSSRApp({ render: () => vnode }).use(createPinia())
    setupSsrStyles(app)
    return renderToString(app)
  }
  const html = await render({})
  assert.match(html, /type="search"/)
  for (const label of ['搜索入库单', '处理人', '开始日期', '结束日期']) assert.match(html, new RegExp(`aria-label="${label}"`))
  assert.match(html, /role="alert"[^>]*>日期范围错误/)
  const setup = vnode.component.setupState
  setup.updateQuery('新关键词'); setup.updateField(fields[0], 1); setup.updateField(fields[1], '2026-10-09'); setup.reset()
  assert.deepEqual(events, [['query', '新关键词'], ['filters', { ...filters, person: 1 }], ['filters', { ...filters, from: '2026-10-09' }], ['reset']])
  assert.deepEqual(filters, { person: null, from: '', to: '' })
  events.length = 0
  await render({ disabled: true })
  vnode.component.setupState.updateQuery('禁止'); vnode.component.setupState.updateField(fields[0], 1); vnode.component.setupState.reset()
  assert.deepEqual(events, [])
  await render({ resetDisabled: true }); vnode.component.setupState.reset(); assert.deepEqual(events, [])
  const searchOnly = await render({ fields: [], issue: '' })
  assert.match(searchOnly, /type="search"/)
  assert.doesNotMatch(searchOnly, /aria-label="处理人"|n-date-picker|role="alert"/)
})
