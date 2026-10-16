import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick, reactive } from 'vue'
import { createPinia } from 'pinia'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import { workspaceSelectKey } from '../src/renderer/src/utils/workspace-select.ts'
import { workspaceTreeOptions, resolveWorkspaceTreeSelection, workspaceTreeSelectTheme } from '../src/renderer/src/utils/workspace-tree-select.ts'
import { themeColorPalette } from '../src/renderer/src/utils/theme-color.ts'

const values = [1, '1', 0, '0', true, false, 'true', null, 'null', '']
const options = () => [
  { label: '全部分类', value: null },
  { label: '电子元件', value: 'EL', searchText: 'electronics 电子元件', children: [
    { label: '电阻', value: 'EL-R', searchText: '电子元件 电阻 RESISTOR' },
    { label: '停用电容', value: 'EL-C', disabled: true }
  ] },
  { label: '结构件', value: 'ME', children: [{ label: '外壳', value: 'ME-CASE' }] }
]

test('树选项保留父子结构、搜索资料与禁用状态，映射不修改原目录', () => {
  const input = options(), before = structuredClone(input)
  input.forEach(row => {
    row.children?.forEach(Object.freeze)
    if (row.children) Object.freeze(row.children)
    Object.freeze(row)
  })
  Object.freeze(input)
  const menu = workspaceTreeOptions(input)
  assert.deepEqual(input, before)
  assert.equal(menu.length, 3)
  assert.equal(menu[0].key, workspaceSelectKey(null))
  assert.equal(menu[1].key, workspaceSelectKey('EL'))
  assert.equal(menu[1].label, '电子元件')
  assert.equal(menu[1].children.length, 2)
  assert.equal(menu[1].children[0].key, workspaceSelectKey('EL-R'))
  assert.match(menu[1].children[0].searchText, /RESISTOR/)
  assert.equal(menu[1].children[1].disabled, true)
  assert.equal(menu[2].children[0].label, '外壳')
  assert.match(menu[2].children[0].searchText, /结构件.*外壳/)
})

test('递归选择区分业务值类型，允许父类与全部项，拒绝禁用、过期及无效键', () => {
  const nested = [{ label: '父级', value: 'parent', children: values.map(value => ({ label: String(value), value })) }]
  assert.equal(resolveWorkspaceTreeSelection(nested, workspaceSelectKey('parent')).value, 'parent')
  assert.equal(new Set(values.map(workspaceSelectKey)).size, values.length)
  for (const value of values) {
    const selected = resolveWorkspaceTreeSelection(nested, workspaceSelectKey(value))
    assert.ok(selected)
    assert.equal(selected.value, value)
    assert.equal(typeof selected.value, typeof value)
  }
  const input = options()
  assert.equal(resolveWorkspaceTreeSelection(input, workspaceSelectKey('EL-C')), undefined)
  assert.equal(resolveWorkspaceTreeSelection(input, workspaceSelectKey('EL-R'), true), undefined)
  assert.equal(resolveWorkspaceTreeSelection(input, workspaceSelectKey('deleted')), undefined)
  // 父节点停用后，菜单与事件边界都要阻断仍保留 enabled 标记的后代。
  const disabledParent = [{ label: '停用大类', value: 'old', disabled: true, children: [{ label: '原子类', value: 'old-child' }] }]
  assert.equal(workspaceTreeOptions(disabledParent)[0].children[0].disabled, true)
  assert.equal(resolveWorkspaceTreeSelection(disabledParent, workspaceSelectKey('old')), undefined)
  assert.equal(resolveWorkspaceTreeSelection(disabledParent, workspaceSelectKey('old-child')), undefined)
  for (const malformed of [null, undefined, 1, [], {}, 'EL-R']) {
    assert.equal(resolveWorkspaceTreeSelection(input, malformed), undefined)
  }
})

test('树选择器的触发框和浮层主题随明暗及强调色切换，调用间不共享可变主题', () => {
  const lightPalette = themeColorPalette('blue', false), darkPalette = themeColorPalette('rose', true)
  const light = workspaceTreeSelectTheme(false, lightPalette), dark = workspaceTreeSelectTheme(true, darkPalette)
  assert.notEqual(light.menuColor, dark.menuColor)
  assert.notEqual(light.peers.InternalSelection.color, dark.peers.InternalSelection.color)
  assert.ok(JSON.stringify(light).includes(lightPalette.accent))
  assert.ok(JSON.stringify(dark).includes(darkPalette.accent))
  assert.ok(JSON.stringify(light).includes(lightPalette.tint))
  assert.ok(JSON.stringify(dark).includes(darkPalette.tint))
  const untouched = workspaceTreeSelectTheme(false, lightPalette)
  light.peers.InternalSelection.color = '#changed-for-test'
  assert.notEqual(untouched.peers.InternalSelection.color, '#changed-for-test')
})

// 持续挂载真实公共组件，菜单、业务键和事件边界由组件实现；仅替换依赖浏览器定位的 Naive 绘制层。
async function fixture(t, extra = {}) {
  const filename = resolve('src/renderer/src/components/workspace/WorkspaceTreeSelect.vue')
  const moduleId = normalizePath(filename) + '.client.ts'
  const content = compileScript(parse(readFileSync(filename, 'utf8'), { filename }).descriptor,
    { id: 'workspace-tree-select-test', inlineTemplate: true }).content
    .replace(/from (['"])naive-ui\1/g, "from 'virtual:workspace-tree-select-naive'")
  const server = await createServer({ configFile: false, plugins: [{ name: 'workspace-tree-select-test', enforce: 'pre',
    resolveId(id) {
      if (id === moduleId) return id
      if (id === 'virtual:workspace-tree-select-naive') return '\0workspace-tree-select-naive'
      if (id.endsWith('/store/theme-store')) return '\0workspace-tree-select-theme'
    },
    load(id) {
      if (id === moduleId) return content
      if (id === '\0workspace-tree-select-naive') return `import {h} from 'vue';export const NTreeSelect={
        props:['value','options','disabled','filterable','placeholder','size','themeOverrides','filter','inputProps','to','fallbackOption'],
        setup:(p,{attrs,slots,expose})=>{expose({focus(){}});return()=>h('tree-select',{...attrs,...p},slots.empty?.())}}`
      // 保留 Pinia 的 storeToRefs 响应式链，不依赖真实系统主题或本机偏好。
      if (id === '\0workspace-tree-select-theme') return `import {defineStore} from 'pinia';export const useThemeStore=defineStore('tree-select-theme',{
        state:()=>({isDarkTheme:false,colorPalette:{accent:'#2255aa',tint:'#e0eaff',activeTint:'#ccd9ff',ring:'#2255aa29'}})})`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Select } = await server.ssrLoadModule(moduleId)
  const { useThemeStore } = await server.ssrLoadModule('\0workspace-tree-select-theme')
  const pinia = createPinia(), theme = useThemeStore(pinia)
  const props = reactive({ modelValue: null, options: options(), disabled: false, ...extra }), events = []
  const element = tag => markRaw({ tag, props: {}, children: [], text: '', parent: null })
  const root = element('root')
  const renderer = createRenderer({ createElement: element, createText: text => ({ ...element('#text'), text }), createComment: () => element('#comment'),
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
    }, remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
    setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
    patchProp(node, key, previous, value) { node.props[key] = value }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null })
  const app = renderer.createApp({ render: () => h(Select, { ...props,
    'onUpdate:modelValue': value => { events.push(['update', value]); props.modelValue = value },
    onChange: value => events.push(['change', value, props.modelValue])
  }) }).use(pinia)
  app.mount(root); t.after(() => app.unmount()); await nextTick()
  const all = node => [node, ...node.children.flatMap(all)]
  const control = () => all(root).find(node => node.tag === 'tree-select')
  const choose = key => control().props['onUpdate:value'](key)
  return { props, events, theme, control, choose, nodes: () => all(root) }
}

test('真实树组件向 Naive 提供分级菜单、全部项、搜索回调及表单可访问名称', async t => {
  const f = await fixture(t, { ariaLabel: '选择物料分类', placeholder: '全部物料分类', size: 'small' })
  const control = f.control().props
  assert.equal(control.value, workspaceSelectKey(null))
  assert.equal(control.options[1].children[0].label, '电阻')
  assert.equal(control.options[1].children[0].key, workspaceSelectKey('EL-R'))
  assert.equal(control.filterable, true)
  assert.equal(control.placeholder, '全部物料分类')
  assert.equal(control.size, 'small')
  assert.equal(control.to, 'body')
  assert.ok(f.nodes().some(node => node.props.role === 'group' && node.props['aria-label'] === '选择物料分类'))
  assert.equal(typeof control.filter, 'function')
  assert.equal(control.filter('resistor', control.options[1].children[0]), true)
  assert.equal(control.filter('电子元件', control.options[1].children[0]), true)
  assert.equal(control.filter('不存在的分类', control.options[1].children[0]), false)
})

test('真实树组件先更新受控值再通知联动，父类和子项回传均保持业务值类型', async t => {
  const f = await fixture(t, { options: [{ label: '类型集合', value: 'parent', children: values.map(value => ({ label: String(value), value })) }] })
  for (const value of ['parent', ...values]) {
    f.events.length = 0
    f.choose(workspaceSelectKey(value)); await nextTick()
    assert.deepEqual(f.events, [['update', value], ['change', value, value]])
    assert.equal(f.props.modelValue, value)
    assert.equal(f.control().props.value, workspaceSelectKey(value))
  }
})

test('禁用和目录更新后保留的旧菜单回调不能写入过期或停用项', async t => {
  const f = await fixture(t), oldUpdate = f.control().props['onUpdate:value']
  for (const key of [workspaceSelectKey('EL-C'), workspaceSelectKey('deleted'), null, 1, 'EL-R']) oldUpdate(key)
  assert.deepEqual(f.events, [])
  f.props.disabled = true; await nextTick()
  assert.equal(f.control().props.disabled, true)
  oldUpdate(workspaceSelectKey('EL-R')); assert.deepEqual(f.events, [])
  f.props.disabled = false
  f.props.options = [{ label: '电子元件', value: 'EL', children: [{ label: '已停用电阻', value: 'EL-R', disabled: true }] }]
  await nextTick(); oldUpdate(workspaceSelectKey('EL-R'))
  assert.deepEqual(f.events, [])
  f.props.options = []; await nextTick(); oldUpdate(workspaceSelectKey('EL'))
  assert.deepEqual(f.events, [])
  f.props.options = [{ label: '停用父类', value: 'EL', disabled: true, children: [{ label: '原电阻分类', value: 'EL-R' }] }]
  await nextTick(); oldUpdate(workspaceSelectKey('EL-R'))
  assert.deepEqual(f.events, [])
  f.props.options = options(); await nextTick(); oldUpdate(workspaceSelectKey('EL-R'))
  assert.deepEqual(f.events, [['update', 'EL-R'], ['change', 'EL-R', 'EL-R']])
})

test('真实树组件在 Pinia 主题变化后同步更新浮层与触发框，关闭搜索透传给控件', async t => {
  const f = await fixture(t, { filterable: false })
  const light = f.control().props.themeOverrides
  assert.equal(f.control().props.filterable, false)
  assert.ok(JSON.stringify(light).includes('#2255aa'))
  f.theme.isDarkTheme = true
  f.theme.colorPalette = themeColorPalette('violet', true)
  await nextTick()
  const dark = f.control().props.themeOverrides
  assert.notEqual(light.menuColor, dark.menuColor)
  assert.notEqual(light.peers.InternalSelection.color, dark.peers.InternalSelection.color)
  assert.ok(JSON.stringify(dark).includes(f.theme.colorPalette.accent))
})
