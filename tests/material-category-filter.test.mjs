import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import { materialCategoryFilterOptions } from '../src/renderer/src/utils/material-category-filter.ts'
import { materialDraft, materialInput, matchesMaterial } from '../src/renderer/src/utils/material-form.ts'

const categories = () => [
  { code: 'EL', name: '电子类', enabled: true, children: [
    { code: 'EL-SR', name: '贴片电阻', enabled: true },
    { code: 'EL-SC', name: '陶瓷电容', enabled: false }
  ] },
  { code: 'ME', name: '结构件', children: [{ code: 'ME-CS', name: '外壳' }] },
  { code: 'LEGACY', name: '历史目录', enabled: false, children: [{ code: 'OLD-X', name: '旧配件', enabled: false }] },
  // 故意让另一大类的子类使用相同前缀，防止筛选退回按字符串猜测归属。
  { code: 'OTHER', name: '其他', children: [{ code: 'EL-RIVAL', name: '独立配件' }] },
  { code: 'EMPTY', name: '空目录', children: [] }
]
const material = (id, category, extra = {}) => ({
  ...materialInput({ ...materialDraft(), name: `物料 ${id}`, category_code: category }, false),
  id, sku: `SKU-${id}`, version: 1, ...extra
})
const selectedIds = (rows, category, query = '', directory = categories()) => rows
  .filter(row => matchesMaterial(row, query, category, directory)).map(row => row.id)

test('分类选项保留大类与子类树，停用及旧格式目录仍可查询且不修改原资料', () => {
  const directory = categories(), before = structuredClone(directory)
  for (const group of directory) {
    group.children.forEach(Object.freeze)
    Object.freeze(group.children)
    Object.freeze(group)
  }
  Object.freeze(directory)
  const options = materialCategoryFilterOptions(directory)
  assert.deepEqual(options.slice(0, 2), [{ value: '', label: '全部分类' }, { value: 'unclassified', label: '未分类' }])
  const electronic = options.find(row => row.value === 'EL')
  assert.equal(electronic.label, '电子类')
  assert.deepEqual(electronic.children.map(row => row.value), ['EL-SR', 'EL-SC'])
  assert.equal(electronic.children[1].label, '陶瓷电容（已停用）')
  const historical = options.find(row => row.value === 'LEGACY')
  assert.equal(historical.label, '历史目录（已停用）')
  assert.equal(historical.children[0].value, 'OLD-X')
  assert.equal(historical.children[0].label, '旧配件（已停用）')
  for (const group of options) {
    assert.notEqual(group.disabled, true, '查询旧记录时不能禁用停用分类')
    for (const child of group.children ?? []) assert.notEqual(child.disabled, true)
  }
  assert.equal(options.find(row => row.value === 'ME').children[0].label, '外壳', '旧目录允许省略启用元数据')
  assert.deepEqual(directory, before)
})

test('大类按真实子类集合匹配，叶子精确匹配，不纳入同前缀或未知旧编码', () => {
  const rows = ['EL-SR', 'EL-SC', 'EL-RIVAL', 'EL-OLD', 'EL', 'ME-CS', 'OLD-X', '']
    .map((category, index) => material(index + 1, category))
  assert.deepEqual(selectedIds(rows, 'EL'), [1, 2])
  assert.deepEqual(selectedIds(rows, 'EL-SR'), [1])
  assert.deepEqual(selectedIds(rows, 'OTHER'), [3])
  assert.deepEqual(selectedIds(rows, 'ME'), [6])
  assert.deepEqual(selectedIds(rows, 'LEGACY'), [7], '停用的大类和子类仍可定位历史记录')
  assert.deepEqual(selectedIds(rows, 'EMPTY'), [])
})

test('全部保留未知旧分类，未分类只匹配空编码，关键词与分类共同限制结果', () => {
  const rows = [
    material(1, 'EL-SR', { manufacturer_part_number: 'RC-0603-10K', package: '0603' }),
    material(2, 'EL-SC', { manufacturer_part_number: 'CAP-100NF', spec_values: [{ name: '容量', value: '100', unit: 'nF', source: '工程图纸' }] }),
    material(3, 'ME-CS', { manufacturer_part_number: 'RC-0603-10K', extra_attributes: [{ name: '颜色', value: '蓝色', unit: '' }] }),
    material(4, 'EL-REMOVED'), material(5, '')
  ]
  assert.deepEqual(selectedIds(rows, ''), [1, 2, 3, 4, 5])
  assert.deepEqual(selectedIds(rows, 'unclassified'), [5], '未知的非空编码不能误入未分类')
  assert.deepEqual(selectedIds(rows, 'EL', '  rc-0603-10k  '), [1], '关键词忽略大小写及首尾空白，但不能越过分类范围')
  assert.deepEqual(selectedIds(rows, 'EL', '0603'), [1])
  assert.deepEqual(selectedIds(rows, 'EL', '工程图纸'), [2])
  assert.deepEqual(selectedIds(rows, 'EL-SC', '陶瓷电容'), [2], '中文分类路径仍参与关键词搜索')
  assert.deepEqual(selectedIds(rows, 'ME', '蓝色'), [3])
  assert.deepEqual(selectedIds(rows, 'EL', '蓝色'), [])
})

const settle = async () => { await nextTick(); await new Promise(done => setImmediate(done)); await nextTick() }
const materials = () => [
  ...Array.from({ length: 25 }, (_, index) => material(index + 1, 'EL-SR', { name: `电阻 ${index + 1}` })),
  ...Array.from({ length: 3 }, (_, index) => material(index + 26, 'EL-SC', { name: `电容 ${index + 1}`, manufacturer_part_number: 'CAP-100NF' })),
  ...Array.from({ length: 4 }, (_, index) => material(index + 29, 'ME-CS', { name: `外壳 ${index + 1}` })),
  material(33, '', { name: '未分类物料' }), material(34, 'EL-REMOVED', { name: '旧分类物料' })
]

// 持续挂载真实页面和分页逻辑；仅替换依赖 DOM 的绘制控件，通过真实更新事件改变查询。
async function fixture(t) {
  const filename = resolve('src/renderer/src/views/workspace/catalog/MaterialsView.vue')
  const moduleId = normalizePath(filename) + '.category-filter.client.ts'
  const content = compileScript(parse(readFileSync(filename, 'utf8'), { filename }).descriptor,
    { id: 'material-category-filter-view', inlineTemplate: true }).content
  const server = await createServer({ configFile: false, plugins: [{ name: 'material-category-filter-test', enforce: 'pre',
    resolveId(id) {
      if (id === moduleId) return id
      if (id === 'naive-ui') return '\0material-filter-naive'
      if (id.endsWith('/store/app-store')) return '\0material-filter-store'
      for (const [name, key] of [['WorkspaceTable', 'table'], ['WorkspaceTreeSelect', 'tree'], ['AppInput', 'input'],
        ['AppButton', 'button'], ['AppModal', 'empty'], ['MaterialEditor', 'empty']]) {
        if (id.endsWith('/' + name + '.vue')) return '\0material-filter-' + key
      }
    },
    load(id) {
      if (id === moduleId) return content
      if (id === '\0material-filter-naive') return 'export const NPopconfirm={render:()=>null}'
      if (id === '\0material-filter-empty') return 'export default {render:()=>null}'
      // 真实 Pinia 的 storeToRefs 链保持不变，不接触本机账号、服务或业务数据库。
      if (id === '\0material-filter-store') return `import {defineStore} from 'pinia';
        import {materialDraft} from '/src/renderer/src/utils/material-form.ts';
        export const usePiniaAppStore=defineStore('material-category-filter',{
          state:()=>({busy:false,error:'',connectionLost:false,materials:[],materialCategories:[],materialUnits:[],suppliers:[],supplierMaterials:[],
            materialEditorDraft:materialDraft(),materialEditingId:undefined,materialEditorOpen:false}),
          actions:{can(){return false},async loadMaterial(){},async saveMaterial(){return false},async deleteMaterial(){},cancelCatalogPreparation(){}}
        })`
      if (id === '\0material-filter-input') return `import {h} from 'vue';export default {
        props:['modelValue'],emits:['update:modelValue'],setup:(p,{attrs,emit})=>()=>h('input',{...attrs,value:p.modelValue,
          onInput:event=>emit('update:modelValue',event.target.value)})}`
      if (id === '\0material-filter-button') return `import {h} from 'vue';export default {
        props:['disabled','type'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,...p},slots.default?.())}`
      if (id === '\0material-filter-tree') return `import {h} from 'vue';export default {
        props:['modelValue','options'],emits:['update:modelValue'],setup:(p,{attrs,emit})=>()=>{
          const node=option=>h('li',{'data-category-node':option.value},[h('button',{
            'data-category-value':option.value,disabled:option.disabled,onClick:()=>emit('update:modelValue',option.value)},option.label),
            option.children?h('ul',option.children.map(node)):null]);
          return h('nav',{...attrs,'data-category-selected':p.modelValue},p.options.map(node))}}`
      if (id === '\0material-filter-table') return `import {h} from 'vue';export default {
        props:['data','columns','pagination'],emits:['page-change'],setup:(p,{slots,emit})=>()=>h('section',{'data-material-table':true},[
          slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),h('table',p.data.map(row=>h('tr',{'data-material-id':row.id},
            p.columns.map(column=>h('td',{'data-column':column.key},slots['cell-'+column.key]?.({row})??String(row[column.key]??'')))))),
          !p.data.length?slots.empty?.():null,
          h('nav',{'data-page':p.pagination.page,'data-total':p.pagination.total},
            Array.from({length:Math.max(1,Math.ceil(p.pagination.total/p.pagination.pageSize))},(_,index)=>h('button',{
              'data-target-page':index+1,onClick:()=>emit('page-change',index+1,p.pagination.pageSize)},String(index+1))))])}`
    }
  }], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: View } = await server.ssrLoadModule(moduleId)
  const { usePiniaAppStore } = await server.ssrLoadModule('\0material-filter-store')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  store.materials = materials(); store.materialCategories = categories()
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
  const app = renderer.createApp({ render: () => h(View) }).use(pinia)
  app.mount(root); t.after(() => app.unmount()); await settle()
  const all = node => [node, ...node.children.flatMap(all)]
  const nodes = () => all(root)
  const text = node => [node.text, ...node.children.map(text)].join('')
  const press = node => {
    assert.ok(node, '测试操作必须来自已挂载控件')
    for (const handler of [node.props.onClick].flat()) handler()
  }
  const choose = async value => { press(nodes().find(node => node.tag === 'button' && node.props['data-category-value'] === value)); await settle() }
  const turnPage = async page => { press(nodes().find(node => node.props['data-target-page'] === page)); await settle() }
  const search = async query => {
    nodes().find(node => node.tag === 'input').props.onInput({ target: { value: query } }); await settle()
  }
  const picker = () => nodes().find(node => node.props['aria-label'] === '筛选物料分类')
  const pagination = () => nodes().find(node => Object.hasOwn(node.props, 'data-total')).props
  const ids = () => nodes().filter(node => node.tag === 'tr').map(node => node.props['data-material-id'])
  return { store, nodes, choose, turnPage, search, picker, pagination, ids, text: () => text(root) }
}

test('真实物料页从分类树事件筛选并回第一页，关键词与大类、子类和未分类共同生效', async t => {
  const f = await fixture(t)
  assert.equal(f.pagination()['data-total'], 34)
  assert.equal(f.ids().length, 20)
  const parent = f.nodes().find(node => node.props['data-category-node'] === 'EL')
  assert.ok(parent.children.some(node => node.tag === 'ul'), '页面传入的分类应保留树形层级')
  await f.turnPage(2)
  assert.equal(f.pagination()['data-page'], 2)
  await f.choose('EL')
  assert.equal(f.picker().props['data-category-selected'], 'EL')
  assert.equal(f.pagination()['data-page'], 1)
  assert.equal(f.pagination()['data-total'], 28)
  assert.deepEqual(f.ids(), Array.from({ length: 20 }, (_, index) => index + 1))
  await f.turnPage(2)
  assert.deepEqual(f.ids(), [21, 22, 23, 24, 25, 26, 27, 28])
  await f.choose('EL-SC')
  assert.equal(f.pagination()['data-page'], 1)
  assert.equal(f.pagination()['data-total'], 3)
  assert.deepEqual(f.ids(), [26, 27, 28])
  assert.match(f.text(), /电子类 \/ 陶瓷电容/)
  await f.search('  cap-100nf  ')
  assert.deepEqual(f.ids(), [26, 27, 28])
  await f.choose('ME')
  assert.equal(f.pagination()['data-total'], 0)
  assert.deepEqual(f.ids(), [])
  assert.match(f.text(), /没有匹配的物料/)
  await f.search('')
  assert.deepEqual(f.ids(), [29, 30, 31, 32])
  await f.choose('unclassified')
  assert.deepEqual(f.ids(), [33])
  await f.choose('')
  assert.equal(f.pagination()['data-total'], 34)
  await f.turnPage(2)
  assert.ok(f.ids().includes(34), '全部分类保留已不在目录中的旧编码物料')
  assert.equal(f.store.materials.length, 34, '展示筛选不能裁剪共享物料名单')
})

test('真实物料页移除当前子类或大类后回到全部和第一页，同时保留搜索词及旧物料', async t => {
  const f = await fixture(t)
  await f.choose('EL-SR'); await f.turnPage(2)
  assert.equal(f.pagination()['data-page'], 2)
  f.store.materialCategories = categories().map(group => group.code === 'EL'
    ? { ...group, children: group.children.filter(child => child.code !== 'EL-SR') } : group)
  await settle()
  assert.equal(f.picker().props['data-category-selected'], '')
  assert.equal(f.pagination()['data-page'], 1)
  assert.equal(f.pagination()['data-total'], 34)
  assert.ok(f.ids().includes(1), '目录删去分类不会隐藏或删除原有物料')
  await f.choose('EL'); await f.search('CAP-100NF')
  assert.deepEqual(f.ids(), [26, 27, 28])
  f.store.materialCategories = f.store.materialCategories.filter(group => group.code !== 'EL')
  await settle()
  assert.equal(f.picker().props['data-category-selected'], '')
  assert.equal(f.pagination()['data-page'], 1)
  assert.deepEqual(f.ids(), [26, 27, 28], '只重置失效分类，不清空用户正在使用的关键词')
  assert.equal(f.nodes().find(node => node.tag === 'input').props.value, 'CAP-100NF')
  assert.equal(f.store.materials.length, 34)
})

test('真实物料页目录仅改名或停用时保留选择和页码，停用子类仍可继续检索旧物料', async t => {
  const f = await fixture(t)
  await f.choose('EL-SR'); await f.turnPage(2)
  f.store.materialCategories = categories().map(group => group.code === 'EL'
    ? { ...group, name: '电子元件', enabled: false, children: group.children.map(child => ({ ...child, enabled: false })) } : group)
  await settle()
  assert.equal(f.picker().props['data-category-selected'], 'EL-SR')
  assert.equal(f.pagination()['data-page'], 2, '有效分类刷新不应把用户送回第一页')
  assert.deepEqual(f.ids(), [21, 22, 23, 24, 25])
  const oldCategory = f.nodes().find(node => node.tag === 'button' && node.props['data-category-value'] === 'EL-SR')
  assert.notEqual(oldCategory.props.disabled, true)
  assert.match(f.text(), /电子元件（已停用）/)
  await f.choose('EL-SC')
  assert.equal(f.pagination()['data-page'], 1)
  assert.deepEqual(f.ids(), [26, 27, 28])
})
