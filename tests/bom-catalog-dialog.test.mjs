import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { bomDraftIssue, bomComponentOptions } from '../src/renderer/src/views/workspace/catalog/bom-form.ts'

const materials = [1, 2, 3].map(id => ({ id, sku: `MAT-${id}`, name: `物料${id}`, unit: '个' }))
const draft = () => ({ product_material_id: 3, base_quantity: '1', note: '版本说明', lines: [{ component_material_id: 1, quantity: '0.125' }] })

// 切换成品、物料失效和手动改量均在请求前检查，避免只依赖下拉禁用外观。
test('BOM 草稿校验自身引用、重复、失效、空明细及数量边界', () => {
  assert.equal(bomDraftIssue(draft(), materials), '')
  for (const update of [
    { product_material_id: 0 }, { product_material_id: 99 }, { base_quantity: '0' },
    { base_quantity: '1.0001' }, { base_quantity: '1000000.001' }, { note: '长'.repeat(201) },
    { lines: [] }, { lines: [{ component_material_id: 3, quantity: '1' }] },
    { lines: [{ component_material_id: 99, quantity: '1' }] },
    { lines: [{ component_material_id: 1, quantity: '1' }, { component_material_id: 1, quantity: '2' }] },
    ...['0', '-1', '', '1.0001', '1000000.001'].map(quantity => ({ lines: [{ component_material_id: 1, quantity }] })),
    { lines: Array.from({ length: 101 }, (_, i) => ({ component_material_id: i + 1, quantity: '1' })) }
  ]) assert.ok(bomDraftIssue({ ...draft(), ...update }, materials), JSON.stringify(update))
  assert.equal(bomDraftIssue({ ...draft(), base_quantity: '1000000', lines: [{ component_material_id: 1, quantity: '0.001' }] }, materials), '')
  const form = draft()
  form.lines.push({ component_material_id: 2, quantity: '2' })
  const options = bomComponentOptions(form, materials, 0)
  assert.equal(options.find(option => option.value === 1).disabled, false)
  assert.equal(options.find(option => option.value === 2).disabled, true)
  assert.equal(options.find(option => option.value === 3).disabled, true)
  form.product_material_id = 1
  assert.match(bomDraftIssue(form, materials), /自身组件/)
  assert.equal(form.lines[0].component_material_id, 1)
})

const storeSource = `import {ref} from 'vue'
export const state={error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),materialCategories:ref([]),materials:ref(${JSON.stringify(materials)}),boms:ref([]),bomForm:ref(${JSON.stringify(draft())}),can:()=>true,localTime:()=>'',activateBom:()=>{},retireBom:()=>{},cancelBom:()=>{}}
export let calls=0
export let fail=true
export const setFail=value=>{fail=value}
state.createBom=async()=>{calls++;if(fail){state.error.value='保存失败';return}state.error.value='';state.notice.value='已保存';state.bomForm.value={product_material_id:0,base_quantity:'1',note:'',lines:[{component_material_id:0,quantity:'1'}]}}
export const useAppStore=()=>state`
const modalSource = `import {defineComponent,h} from 'vue'
export const captured={}
export const NModal=defineComponent({props:['show','title'],setup(p,{slots,attrs}){Object.assign(captured,{props:p,slots,attrs});return()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}})`
const tableSource = `import {defineComponent,h} from 'vue'
export const tables=[]
export default defineComponent({props:['title','data','columns'],setup(p,{slots}){return()=>{tables.push({props:p,slots});return h('section',{'data-table':p.title},[slots.actions?.(),slots.heading?.(),...p.data.map(row=>h('article',p.columns.map(c=>slots['cell-'+c.key]?.({row}))))])}}})`
const buttonSource = `import {defineComponent,h} from 'vue'
export const buttons=[]
export default defineComponent({props:['type','disabled'],setup(p,{slots,attrs}){return()=>{const content=slots.default?.();buttons.push({props:p,attrs,content});return h('button',{...attrs,type:p.type,disabled:p.disabled},content)}}})`
const inputSource = `import {defineComponent,h} from 'vue'
export const inputs=[]
export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>{inputs.push({props:p,attrs});return h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}}})`
const selectSource = `import {defineComponent,h} from 'vue'
export default defineComponent({props:['modelValue','options','disabled'],setup(p,{attrs}){return()=>h('select',{...attrs,'data-selected':p.modelValue,disabled:p.disabled},p.options?.map(o=>h('option',{value:o.value,disabled:o.disabled},o.label)))}})`

// 真实 BOM 页面与公共弹窗展开插槽；替换桌面桥接，验证事件、草稿和防护逻辑。
test('BOM 共用弹窗编辑原草稿，删除后不串行，保存失败保留，成功关闭', async t => {
  const server = await createServer({ configFile:false, plugins:[{
    name:'bom-dialog-fixtures', enforce:'pre',
    transform(code,id) {
      if (id.endsWith('/ProductionBomsView.vue')) return code.replace('const createOpen = ref(false)','const createOpen = ref(true)')
      if (id.endsWith('/WorkspaceDocumentDialog.vue')) return code.replace("'naive-ui'","'virtual:bom-modal'")
    },
    resolveId(id,importer) {
      if(id==='virtual:bom-modal')return '\0bom-modal'
      if(!importer?.includes('/src/renderer/'))return
      for(const [suffix,key] of [['/store/app-store','store'],['/WorkspaceTable.vue','table'],['/AppButton.vue','button'],['/AppInput.vue','input'],['/WorkspaceMaterialSelect.vue','select']])if(id.endsWith(suffix))return '\0bom-'+key
    },
    load(id) {return {'\0bom-store':storeSource,'\0bom-modal':modalSource,'\0bom-table':tableSource,'\0bom-button':buttonSource,'\0bom-input':inputSource,'\0bom-select':selectSource}[id]}
  },vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom' })
  t.after(()=>server.close())
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/ProductionBomsView.vue')
  const store=await server.ssrLoadModule('\0bom-store')
  const {state}=store
  const {buttons}=await server.ssrLoadModule('\0bom-button')
  const {inputs}=await server.ssrLoadModule('\0bom-input')
  const {tables}=await server.ssrLoadModule('\0bom-table')
  const {captured}=await server.ssrLoadModule('\0bom-modal')
  const text=nodes=>(nodes??[]).map(n=>typeof n.children==='string'?n.children:Array.isArray(n.children)?text(n.children):'').join('')
  let viewVNode
  const render=async()=>{buttons.length=0;inputs.length=0;tables.length=0;viewVNode=h(View);return renderToString(createSSRApp({render:()=>viewVNode}))}
  assert.match(await render(),/data-table="物料明细"/)
  assert.match(await render(),/基准产出数量/)
  const original=state.bomForm.value.lines[0]
  const add=()=>buttons.find(b=>text(b.content).includes('添加物料')).attrs.onClick()
  add()
  assert.equal(state.bomForm.value.lines.length,2)
  assert.equal(state.bomForm.value.lines[0],original)
  state.bomForm.value.lines[1].component_material_id=2
  const second=state.bomForm.value.lines[1]
  await render()
  const rows=tables.find(table=>table.props.title==='物料明细').props.data
  assert.equal(rows[1].line,second)
  buttons.find(b=>text(b.content).includes('移除')).attrs.onClick()
  await render()
  assert.equal(state.bomForm.value.lines[0],second)
  inputs.find(input=>input.attrs['aria-label']==='基准用量').attrs['onUpdate:modelValue']('2.500')
  assert.equal(second.quantity,'2.500')
  state.busy.value=true
  await render();add()
  assert.equal(state.bomForm.value.lines.length,1)
  state.busy.value=false;state.connectionLost.value=true
  assert.match(await render(),/<fieldset disabled/)
  add();assert.equal(state.bomForm.value.lines.length,1)
  state.connectionLost.value=false
  state.bomForm.value.lines=Array.from({length:100},()=>({component_material_id:1,quantity:'1'}))
  await render();add();assert.equal(state.bomForm.value.lines.length,100)
  state.bomForm.value=draft()
  await render()
  const saved=state.bomForm.value
  const form=captured.slots.default()[0]
  const submit=()=>form.props.onSubmit({preventDefault(){}})
  state.connectionLost.value=true
  await submit();assert.equal(store.calls,0)
  state.connectionLost.value=false
  state.bomForm.value.product_material_id=1
  await submit();assert.equal(store.calls,0)
  state.bomForm.value.product_material_id=3
  await submit();assert.equal(store.calls,1)
  assert.equal(state.bomForm.value,saved)
  assert.equal(captured.props.show,true)
  store.setFail(false)
  await submit();assert.equal(store.calls,2)
  assert.equal(viewVNode.component.setupState.createOpen,false)
  state.can=()=>false
  assert.doesNotMatch(await render(),/data-modal=/)
})
