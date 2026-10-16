import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick, reactive } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'

const line = (id, material, name, extra = {}) => ({ id, component_material_id: material,
  sku: `MAT-${material}`, material_name: name, unit: '件', quantity: '1', ...extra })
const bom = (id, material, lines, extra = {}) => ({ id, product_material_id: material,
  product_name: `产出${material}`, product_sku: `MAT-${material}`, product_unit: '台',
  version: 1, base_quantity: '1', status: 'active', lines, ...extra })
const settle = async () => { await nextTick(); await new Promise(done => setImmediate(done)); await nextTick() }

// 持续挂载真实组成组件与递归算法；只替换绘制层，直接保留已渲染按钮回调以检查迟到事件。
async function fixture(t) {
  const filename = resolve('src/renderer/src/views/workspace/catalog/ProductBomStructure.vue')
  const moduleId = normalizePath(filename) + '.material-detail.client.ts'
  const content = compileScript(parse(readFileSync(filename, 'utf8'), { filename }).descriptor,
    { id: 'bom-material-details-test', inlineTemplate: true }).content
    .replace(/from (['"])naive-ui\1/g, "from 'virtual:bom-material-naive'")
  const server = await createServer({ configFile: false, plugins: [{ name: 'bom-material-details-test', enforce: 'pre',
    resolveId(id) {
      if (id === moduleId) return id
      if (id === 'virtual:bom-material-naive') return '\0bom-material-naive'
      if (id.startsWith('~icons/')) return '\0bom-material-icon'
      if (id.endsWith('/utils/dialog-origin')) return '\0bom-material-origin'
      for (const [name, key] of [['WorkspaceTable', 'table'], ['AppButton', 'button'], ['AppCollapseItem', 'collapse']]) {
        if (id.endsWith('/' + name + '.vue')) return '\0bom-material-' + key
      }
    },
    load(id) {
      if (id === moduleId) return content
      if (id === '\0bom-material-naive') return `import {h} from 'vue';export const NCollapse={setup:(p,{slots})=>()=>h('section',slots.default?.())}`
      if (id === '\0bom-material-icon') return `import {h} from 'vue';export default {render:()=>h('svg',{'aria-hidden':'true'})}`
      if (id === '\0bom-material-origin') return `export const origins=[];export function captureDialogOrigin(key,event){origins.push({key,event})}`
      if (id === '\0bom-material-collapse') return `import {h} from 'vue';export default {props:['title'],setup:(p,{slots})=>()=>h('section',[h('h4',p.title),slots.default?.()])}`
      if (id === '\0bom-material-button') return `import {h} from 'vue';export default {props:['disabled','type','variant'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,...p},slots.default?.())}`
      if (id === '\0bom-material-table') return `import {h} from 'vue';export default {props:['data','columns'],setup:(p,{slots})=>()=>h('table',[
        h('thead',h('tr',p.columns.map(column=>h('th',{'data-column':column.key,'data-width':column.width},column.title)))),
        h('tbody',p.data.map(row=>h('tr',{'data-key':row.key},p.columns.map(column=>h('td',{'data-column':column.key},slots['cell-'+column.key]?.({row}))))))])}`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Structure } = await server.ssrLoadModule(moduleId)
  const { origins } = await server.ssrLoadModule('\0bom-material-origin')
  const board = bom(2, 20, [line(21, 30, '板内电阻')])
  const rootBom = bom(1, 10, [line(11, 20, 'PCB 控制板', { component_bom_id: 2 }), line(12, 40, '普通外壳')])
  const props = reactive({ bom: structuredClone(rootBom), catalog: [structuredClone(board)], disabled: false })
  const materials = [], recipes = []
  const element = tag => markRaw({ tag, props: {}, children: [], text: '', parent: null }), root = element('root')
  const renderer = createRenderer({ createElement: element, createText: text => ({ ...element('#text'), text }), createComment: () => element('#comment'),
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node); node.parent = parent
    }, remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
    setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
    patchProp(node, key, previous, value) { node.props[key] = value }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null })
  const app = renderer.createApp({ render: () => h(Structure, { ...props,
    onMaterial: row => materials.push(row), onOpen: id => recipes.push(id)
  }) })
  app.mount(root); t.after(() => app.unmount()); await settle()
  const all = node => [node, ...node.children.flatMap(all)]
  const nodes = () => all(root)
  const text = node => [node.text, ...node.children.map(text)].join('')
  const row = key => nodes().find(node => node.tag === 'tr' && node.props['data-key'] === key)
  const cell = (key, column) => all(row(key)).find(node => node.tag === 'td' && node.props['data-column'] === column)
  const button = label => nodes().find(node => node.tag === 'button' && node.props['aria-label'] === label)
  const press = node => {
    assert.ok(node, '操作必须来自真实渲染的按钮')
    const event = { target: node, currentTarget: node }
    for (const callback of [node.props.onClickCapture, node.props.onClick].flat().filter(Boolean)) callback(event)
    return event
  }
  return { props, board, rootBom, materials, recipes, origins, nodes, descendants: all, text, row, cell, button, press,
    bodyRows: () => nodes().filter(node => node.tag === 'tr' && node.props['data-key']) }
}

test('树形控制与物料编号合并最左列，名称保持独立，普通物料和 PCB 点击只打开对应物料', async t => {
  const f = await fixture(t)
  const headings = f.nodes().filter(node => node.tag === 'th')
  assert.deepEqual(headings.map(node => node.props['data-column']), ['sku', 'component', 'quantity', 'unit', 'recipe'])
  assert.equal(f.text(headings[0]), '物料编号')
  assert.equal(Number(headings[0].props['data-width']), 200)
  // 箭头和圆点并入编号列，名称列不再预留树形装饰；普通叶节点仅有编号详情按钮。
  assert.ok(f.descendants(f.cell('1/11', 'sku')).includes(f.button('展开PCB 控制板的组成')))
  const ordinarySku = f.descendants(f.cell('1/12', 'sku'))
  assert.ok(ordinarySku.some(node => String(node.props.class ?? '').includes('structure-leaf')))
  assert.deepEqual(ordinarySku.filter(node => node.tag === 'button'), [f.button('查看物料 MAT-40 的详情')])
  for (const key of ['1/11', '1/12']) {
    assert.ok(f.descendants(f.cell(key, 'sku')).some(node => Object.values(node.props.style ?? {}).includes('0px')))
    const nameNodes = f.descendants(f.cell(key, 'component'))
    assert.equal(nameNodes.some(node => node.tag === 'button' || node.tag === 'svg'), false)
    assert.equal(nameNodes.some(node => /structure-(?:toggle|chevron|leaf|tree)/.test(String(node.props.class ?? ''))), false)
    assert.equal(nameNodes.some(node => node.props.style && ('paddingLeft' in node.props.style || '--structure-indent' in node.props.style)), false)
  }
  assert.match(f.text(f.cell('1/11', 'component')), /PCB 控制板/)
  assert.doesNotMatch(f.text(f.cell('1/11', 'component')), /MAT-20/)
  assert.match(f.text(f.cell('1/11', 'sku')), /MAT-20/)
  const openBoard = f.button('查看物料 MAT-20 的详情')
  assert.equal(openBoard.props.variant, 'text')
  const event = f.press(openBoard); await settle()
  assert.equal(f.materials.length, 1)
  assert.equal(f.materials[0].materialId, 20)
  assert.equal(f.materials[0].sku, 'MAT-20')
  assert.equal(f.materials[0].name, 'PCB 控制板')
  assert.equal(f.materials[0].key, '1/11')
  assert.equal(f.bodyRows().length, 2, '物料编号点击不能顺带展开下层')
  assert.deepEqual(f.recipes, [])
  assert.equal(f.origins.at(-1).key, 'inventory-material')
  assert.equal(f.origins.at(-1).event, event)
  f.press(f.button('查看物料 MAT-40 的详情')); await settle()
  assert.deepEqual(f.materials.map(row => row.materialId), [20, 40])
  assert.equal(f.bodyRows().length, 2)
  assert.deepEqual(f.recipes, [])
})

test('嵌套编号定位真实组件，展开、配方详情和物料详情各自独立', async t => {
  const f = await fixture(t)
  f.press(f.button('展开PCB 控制板的组成')); await settle()
  assert.equal(f.bodyRows().length, 3)
  assert.deepEqual(f.materials, []); assert.deepEqual(f.recipes, [])
  // 展开后仅编号格内的树形分支缩进，名称列始终沿同一条文本起点排列。
  const skuHeading = f.nodes().find(node => node.tag === 'th' && node.props['data-column'] === 'sku')
  assert.equal(Number(skuHeading.props['data-width']), 216)
  const nestedTree = f.descendants(f.cell('1/11/21', 'sku'))
  assert.ok(nestedTree.some(node => Object.values(node.props.style ?? {}).includes('16px')))
  assert.ok(nestedTree.some(node => String(node.props.class ?? '').includes('is-nested')))
  assert.deepEqual(nestedTree.filter(node => node.tag === 'button'), [f.button('查看物料 MAT-30 的详情')])
  const nestedName = f.descendants(f.cell('1/11/21', 'component'))
  assert.equal(nestedName.some(node => node.tag === 'button' || node.tag === 'svg' || /structure-(?:toggle|chevron|leaf|tree)/.test(String(node.props.class ?? ''))), false)
  assert.equal(nestedName.some(node => node.props.style && ('paddingLeft' in node.props.style || '--structure-indent' in node.props.style)), false)
  assert.match(f.text(f.cell('1/11/21', 'component')), /板内电阻/)
  assert.doesNotMatch(f.text(f.cell('1/11/21', 'component')), /MAT-30/)
  f.press(f.button('查看物料 MAT-30 的详情')); await settle()
  assert.equal(f.materials.length, 1)
  assert.equal(f.materials[0].materialId, 30)
  assert.equal(f.materials[0].key, '1/11/21')
  assert.equal(f.materials[0].depth, 1)
  assert.equal(f.bodyRows().length, 3)
  assert.deepEqual(f.recipes, [])
  const recipe = f.nodes().find(node => node.tag === 'button' && f.text(node) === '固定 V1')
  f.press(recipe); await settle()
  assert.deepEqual(f.recipes, [2])
  assert.equal(f.materials.length, 1)
  assert.equal(f.bodyRows().length, 3)
})

test('断线禁用时旧编号回调无效，恢复后仍能查看当前物料', async t => {
  const f = await fixture(t), oldButton = f.button('查看物料 MAT-20 的详情'), oldClick = oldButton.props.onClick
  f.props.disabled = true; await settle()
  assert.equal(f.button('查看物料 MAT-20 的详情').props.disabled, true)
  oldClick({ target: oldButton, currentTarget: oldButton }); await settle()
  assert.deepEqual(f.materials, []); assert.deepEqual(f.recipes, [])
  assert.equal(f.bodyRows().length, 2)
  f.props.disabled = false; await settle()
  f.press(f.button('查看物料 MAT-20 的详情')); await settle()
  assert.equal(f.materials[0].materialId, 20)
})

test('收起已展开分支及切换 BOM 后，迟到的旧编号不能打开另一行或旧版本物料', async t => {
  const f = await fixture(t)
  f.press(f.button('展开PCB 控制板的组成')); await settle()
  const nested = f.button('查看物料 MAT-30 的详情'), nestedClick = nested.props.onClick
  const board = f.button('查看物料 MAT-20 的详情'), boardClick = board.props.onClick
  f.press(f.button('收起PCB 控制板的组成')); await settle()
  nestedClick({ target: nested, currentTarget: nested }); await settle()
  assert.deepEqual(f.materials, [])
  f.props.bom = { ...structuredClone(f.rootBom), id: 9, version: 2 }; await settle()
  boardClick({ target: board, currentTarget: board }); await settle()
  assert.deepEqual(f.materials, [])
  assert.equal(f.bodyRows().length, 2)
  assert.equal(f.button('展开PCB 控制板的组成').props['aria-expanded'], false)
})

test('同一行身份更新后拒绝旧回调，物料编号、名称和分支键均需属于当前快照', async t => {
  for (const [label, patch] of [
    ['物料身份', { component_material_id: 99 }], ['编号', { sku: 'MAT-RENAMED' }],
    ['名称', { material_name: '新名称' }], ['分支', { id: 99 }]
  ]) await t.test(label, async t => {
    const f = await fixture(t), button = f.button('查看物料 MAT-20 的详情'), oldClick = button.props.onClick
    f.props.bom = { ...structuredClone(f.rootBom), lines: f.rootBom.lines.map((row, index) => index ? { ...row } : { ...row, ...patch }) }
    await settle()
    oldClick({ target: button, currentTarget: button }); await settle()
    assert.deepEqual(f.materials, [])
    assert.deepEqual(f.recipes, [])
  })
})
