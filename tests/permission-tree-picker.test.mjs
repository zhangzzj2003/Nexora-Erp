import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'
import { buildPermissionTree } from '../src/renderer/src/utils/permission-tree.ts'

test('真实权限树按类全选和半选，父级联动并保留只读与忙碌保护', async t => {
  const filename = resolve('src/renderer/src/components/workspace/PermissionTreePicker.vue')
  const id = normalizePath(filename) + '.client.ts'
  const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
  // 包依赖在 SSR 下可能直接外置，显式替换导入名确保控件桩仅用于此测试。
  const compiled = compileScript(descriptor, { id: 'permission-picker-test', inlineTemplate: true }).content
    .replace(/(['"])naive-ui\1/g, "'permission-picker-checkbox'")
  // 内存渲染只替换控件外壳；权限树的真实展开、分类、勾选和保护回调均运行。
  const server = await createServer({ configFile: false, plugins: [{ name: 'permission-picker-test', enforce: 'pre',
    resolveId(value) {
      if (value === id) return id
      if (value.endsWith('/AppButton.vue')) return '\0picker-button'
      if (value === 'permission-picker-checkbox') return '\0picker-checkbox'
    },
    load(value) {
      if (value === id) return compiled
      if (value === '\0picker-button') return `import {defineComponent,h} from 'vue';export default defineComponent({setup(_,ctx){return()=>h('button',ctx.attrs,ctx.slots.default?.())}})`
      if (value === '\0picker-checkbox') return `import {defineComponent,h} from 'vue';export const NCheckbox=defineComponent({setup(_,ctx){return()=>h('checkbox',ctx.attrs,ctx.slots.default?.())}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Picker } = await server.ssrLoadModule(id)
  const element = type => ({ type, props: {}, children: [], parent: null, text: '' })
  const renderer = createRenderer({
    createElement: element, createText: text => ({ ...element('#text'), text }), createComment: text => ({ ...element('#comment'), text }),
    setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.children = []; node.text = text },
    patchProp: (node, key, _, value) => { node.props[key] = value }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    insert(node, parent, anchor = null) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      node.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
    },
    remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1) }
  })
  const path = [{ code: 'warehouse', label: '仓库管理' }, { code: 'other_inbound', label: '其他入库' }]
  const modules = buildPermissionTree(['view', 'create', 'post', 'review', 'verify', 'approve'].map(action => ({
    code: `other_inbound.${action}`, label: action, group_path: path
  })))
  const state = reactive({ selected: ['legacy.unknown'], readonly: false, disabled: false })
  const updates = []
  const root = element('root')
  const app = renderer.createApp({ render: () => h(Picker, { modules, modelValue: state.selected, readonly: state.readonly, disabled: state.disabled,
    'onUpdate:modelValue': codes => { updates.push(codes); state.selected = codes }
  }) })
  app.mount(root)
  t.after(() => app.unmount())
  const flatten = node => [node, ...node.children.flatMap(flatten)]
  const text = node => (node.type === '#comment' ? '' : node.text) + node.children.map(text).join('')
  const checkbox = label => flatten(root).find(node => node.type === 'checkbox' && node.props['aria-label'] === label)
  const change = async (node, checked) => { assert.ok(node); node.props['onUpdate:checked'](checked); await nextTick() }
  // 键盘与鼠标共用同一个按钮回调，展开动作不会触发保存或修改授权。
  for (const title of ['仓库管理', '其他入库']) {
    const button = flatten(root).find(node => node.type === 'button' && text(node).includes(title))
    button.props.onClick(); await nextTick()
    assert.equal(button.props['aria-expanded'], true)
  }
  assert.match(text(root), /读写操作/)
  assert.match(text(root), /审核操作/)
  await change(checkbox('选择其他入库全部读写操作'), true)
  assert.deepEqual(new Set(state.selected), new Set(['legacy.unknown', 'other_inbound.view', 'other_inbound.create', 'other_inbound.post']))
  assert.equal(checkbox('选择其他入库全部审核操作').props.checked, false)
  assert.equal(checkbox('选择其他入库全部操作').props.indeterminate, true)
  const review = flatten(root).find(node => node.type === 'checkbox' && text(node) === 'review')
  await change(review, true)
  assert.equal(checkbox('选择其他入库全部审核操作').props.indeterminate, true)
  await change(checkbox('选择其他入库全部审核操作'), true)
  assert.equal(checkbox('选择仓库管理全部操作').props.checked, true)
  await change(checkbox('选择其他入库全部读写操作'), false)
  assert.deepEqual(new Set(state.selected), new Set(['legacy.unknown', 'other_inbound.review', 'other_inbound.verify', 'other_inbound.approve']))
  for (const flag of ['readonly', 'disabled']) {
    state[flag] = true; await nextTick()
    const count = updates.length
    for (const node of flatten(root).filter(node => node.type === 'checkbox')) {
      assert.equal(node.props.disabled, true)
      await change(node, true)
    }
    assert.equal(updates.length, count)
    state[flag] = false; await nextTick()
  }
  await change(checkbox('选择仓库管理全部操作'), false)
  assert.deepEqual(state.selected, ['legacy.unknown'])
})
