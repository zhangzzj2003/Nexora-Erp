import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick, reactive } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'

// 持续挂载真实组件；节点仅模拟查询和尺寸，避免把浏览器布局能力误写成单元测试结论。
function nativeRenderer() {
  const all=node=>[node,...node.children.flatMap(all)]
  const element=tag=>markRaw({tag,children:[],props:{},text:'',parent:null,clientWidth:800,scrollWidth:800,scrollLeft:0,
    querySelectorAll(selector){return all(this).slice(1).filter(node=>String(node.props.class??'').split(/\s+/).includes(selector.slice(1)))},
    querySelector(selector){return this.querySelectorAll(selector)[0]??null}})
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
    insert(node,parent,anchor){
      if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)
      const index=anchor?parent.children.indexOf(anchor):-1
      parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent
    },remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null},
    setText(node,text){node.text=text},setElementText(node,text){node.text=text;node.children=[]},
    patchProp(node,key,old,value){node.props[key]=value},parentNode:node=>node.parent,
    nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null})
  return {renderer,root:element('root')}
}

const settle=async()=>{await nextTick();await nextTick();await new Promise(done=>setImmediate(done));await nextTick()}

async function fixture(t) {
  const modules=['views/workspace/catalog/BomInlineForm.vue','components/workspace/WorkspaceTable.vue'].map(file=>{
    const filename=resolve('src/renderer/src',file)
    const content=compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,{id:file,inlineTemplate:true}).content
      .replaceAll("'vxe-table/es/table'","'virtual:inline-layout-vxe'")
      .replaceAll("'vxe-table/es/column'","'virtual:inline-layout-column'")
      .replaceAll("'@vxe-ui/core'","'virtual:inline-layout-core'")
      .replaceAll("'vxe-table/es/locale/lang/zh-CN'","'virtual:inline-layout-locale'")
    return [normalizePath(filename)+'.client.ts',content]
  })
  const sources=new Map(modules)
  const server=await createServer({configFile:false,plugins:[{name:'bom-inline-layout',enforce:'pre',resolveId(id){
    if(sources.has(id))return id
    if(id.endsWith('/WorkspaceTable.vue'))return '\0inline-layout-table'
    if(id.endsWith('/AppButton.vue'))return '\0inline-layout-button'
    if(id.endsWith('/WorkspacePagination.vue'))return '\0inline-layout-empty'
    if(id==='virtual:inline-layout-vxe')return '\0inline-layout-vxe'
    if(id==='virtual:inline-layout-column')return '\0inline-layout-column'
    if(id==='virtual:inline-layout-core')return '\0inline-layout-core'
    if(id==='virtual:inline-layout-locale')return '\0inline-layout-locale'
  },load(id){
    if(sources.has(id))return sources.get(id)
    if(id==='\0inline-layout-table')return `import {h} from 'vue';export const refreshes=[];export default {props:['data','columns'],setup:(p,{slots,expose})=>{
      expose({refreshLayout:async()=>{refreshes.push('refresh')}});return()=>h('section',{class:'workspace-table-stub'},[
        slots.heading?.(),slots.actions?.(),h('table',{class:'vxe-table--body'},p.data.map(row=>h('tr',p.columns.map(column=>h('td',slots['cell-'+column.key]?.({row}))))))])}}`
    if(id==='\0inline-layout-button')return `import {h} from 'vue';export default {props:['disabled','type'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,disabled:p.disabled,type:p.type},slots.default?.())}`
    if(id==='\0inline-layout-vxe')return `import {h} from 'vue';export const recalculations=[],rowMeasurements=[],layoutCalls=[];export default {props:['data'],setup:(p,{slots,attrs,expose})=>{
      expose({recalcRowHeight:async rows=>{rowMeasurements.push(rows);layoutCalls.push('rows')},
        recalculate:async full=>{recalculations.push(full);layoutCalls.push('layout')},getColumns:()=>[],refreshColumn:async()=>{},
        getScrollData:()=>({clientWidth:800,scrollWidth:800,scrollLeft:0}),scrollTo:async()=>{}});
      return()=>h('div',attrs,[h('table',{class:'vxe-table--body'}),slots.default?.()])}}`
    if(id==='\0inline-layout-column')return `import {h} from 'vue';export default {render:()=>h('span')}`
    if(id==='\0inline-layout-core')return `export const VxeUI={setI18n(){},setLanguage(){}}`
    if(id==='\0inline-layout-locale')return 'export default {}'
    if(id==='\0inline-layout-empty')return 'export default {render:()=>null}'
  }}],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const previous=globalThis.ResizeObserver,previousMutation=globalThis.MutationObserver,observers=[],mutations=[]
  // 回调由测试显式触发，记录目标与断开次数，覆盖收起、重新显示以及卸载。
  globalThis.ResizeObserver=class {
    constructor(callback){this.callback=callback;this.targets=[];this.disconnects=0;observers.push(this)}
    observe(target){this.targets.push(target)}
    disconnect(){this.disconnects++;this.targets=[]}
    resize(height=91){this.callback(this.targets.map(target=>({target,contentRect:{height}})),this)}
  }
  globalThis.MutationObserver=class {
    constructor(callback){this.callback=callback;this.targets=[];this.disconnects=0;mutations.push(this)}
    observe(target,options){this.targets.push({target,options})}
    disconnect(){this.disconnects++;this.targets=[]}
    mutate(){this.callback([{type:'childList'}],this)}
  }
  t.after(()=>{
    if(previous===undefined)delete globalThis.ResizeObserver;else globalThis.ResizeObserver=previous
    if(previousMutation===undefined)delete globalThis.MutationObserver;else globalThis.MutationObserver=previousMutation
  })
  const {default:Inline}=await server.ssrLoadModule(modules[0][0])
  const {default:Table}=await server.ssrLoadModule(modules[1][0])
  const {refreshes}=await server.ssrLoadModule('\0inline-layout-table')
  const {recalculations,rowMeasurements,layoutCalls}=await server.ssrLoadModule('\0inline-layout-vxe')
  function mount(component,props,slots={}) {
    const {renderer,root}=nativeRenderer()
    let instance,unmounted=false
    const app=renderer.createApp({render:()=>h(component,{...props,ref:value=>{instance=value}},slots)})
    app.mount(root)
    const unmount=()=>{if(!unmounted){unmounted=true;app.unmount()}}
    t.after(unmount)
    return {root,unmount,get instance(){return instance}}
  }
  return {Inline,Table,observers,mutations,refreshes,recalculations,rowMeasurements,layoutCalls,mount}
}

const materialSlot=({row})=>h('div',{class:'workspace-material-select',key:row.name},row.name)

test('行内 BOM 观察物料自然高度，展开收起刷新且旧表单与卸载回调均失效',async t=>{
  const f=await fixture(t),props=reactive({show:true,title:'首次建立 BOM',data:[{name:'控制板'}],columns:[{key:'name',title:'组件'}]})
  const mounted=f.mount(f.Inline,props,{'cell-name':materialSlot})
  await settle()
  assert.equal(f.observers.length,1)
  assert.equal(f.mutations.length,1)
  const first=f.observers[0],firstMutation=f.mutations[0],firstMaterial=mounted.root.querySelector('.workspace-material-select')
  assert.ok(firstMaterial,'真实物料单元格已挂载')
  assert.deepEqual(first.targets,[firstMaterial])
  assert.notEqual(first.targets[0],mounted.root.querySelector('.vxe-table--body'),'固定高度表体不能作为自然高度观察目标')
  assert.deepEqual(firstMutation.targets,[{target:mounted.root.querySelector('.bom-inline-form'),options:{childList:true,subtree:true}}])
  // 模拟自然内容展开至 239px 再收起至 91px，两次都必须刷新，不依赖固定表体是否变化。
  first.resize(239);await settle()
  assert.deepEqual(f.refreshes,['refresh'])
  first.resize(91);await settle()
  assert.deepEqual(f.refreshes,['refresh','refresh'])
  const disconnects=first.disconnects
  props.show=false;await settle()
  assert.ok(first.disconnects>disconnects)
  assert.equal(firstMutation.disconnects,1)
  assert.equal(mounted.root.querySelector('.workspace-material-select'),null)
  first.resize();firstMutation.mutate();await settle()
  assert.equal(f.refreshes.length,2,'隐藏后迟到的旧回调不应调用已移除表格')
  props.show=true;await settle()
  assert.equal(f.observers.length,2)
  assert.equal(f.mutations.length,2)
  const second=f.observers[1],secondMutation=f.mutations[1],secondMaterial=mounted.root.querySelector('.workspace-material-select')
  assert.notEqual(secondMaterial,firstMaterial)
  assert.deepEqual(second.targets,[secondMaterial])
  first.resize();firstMutation.mutate();await settle()
  assert.equal(f.refreshes.length,2,'重新显示后旧表单回调不能作用于新表格')
  assert.deepEqual(second.targets,[secondMaterial],'旧 mutation 回调不能重新绑定新观察器')
  second.resize();await settle();assert.equal(f.refreshes.length,3)
  const secondDisconnects=second.disconnects
  mounted.unmount();await settle()
  assert.ok(second.disconnects>secondDisconnects)
  assert.equal(secondMutation.disconnects,1)
  second.resize();secondMutation.mutate();await settle()
  assert.equal(f.refreshes.length,3,'卸载后不应继续刷新')
})

test('VXE 异步新增、删除与重建行后 mutation 重新观察当前物料节点，不监听样式写回',async t=>{
  const f=await fixture(t),props=reactive({show:true,title:'BOM',data:[],columns:[{key:'name',title:'组件'}]})
  const mounted=f.mount(f.Inline,props,{'cell-name':materialSlot})
  await settle()
  const resize=f.observers[0],mutation=f.mutations[0]
  assert.deepEqual(resize.targets,[])
  assert.deepEqual(mutation.targets[0].options,{childList:true,subtree:true})
  assert.equal('attributes' in mutation.targets[0].options,false)
  props.data.push({name:'控制板'},{name:'电源板'});await settle()
  mutation.mutate()
  const oldMaterials=mounted.root.querySelectorAll('.workspace-material-select')
  assert.equal(oldMaterials.length,2)
  assert.deepEqual(resize.targets,oldMaterials)
  resize.resize();await settle();assert.equal(f.refreshes.length,1)
  props.data.splice(0,1);await settle();mutation.mutate()
  assert.equal(resize.targets.length,1)
  assert.equal(resize.targets[0],mounted.root.querySelector('.workspace-material-select'))
  assert.ok(!resize.targets.includes(oldMaterials[0]))
  props.data=[{name:'重新构建的物料'}];await settle();mutation.mutate()
  assert.equal(resize.targets.length,1)
  assert.ok(!oldMaterials.includes(resize.targets[0]))
  assert.deepEqual(resize.targets,mounted.root.querySelectorAll('.workspace-material-select'))
  props.data=[];await settle();mutation.mutate()
  assert.deepEqual(resize.targets,[])
})

test('初始隐藏或在挂载测量前收起时不残留物料与内容观察器',async t=>{
  const f=await fixture(t),props=reactive({show:false,title:'BOM',data:[],columns:[]})
  const mounted=f.mount(f.Inline,props)
  await settle();assert.equal(f.observers.length,0)
  assert.equal(f.mutations.length,0)
  props.show=true;await nextTick();props.show=false;await settle()
  assert.ok(f.observers.every(observer=>observer.disconnects>0))
  assert.ok(f.mutations.every(observer=>observer.disconnects>0))
  assert.equal(mounted.root.querySelector('.vxe-table--body'),null)
  assert.deepEqual(f.refreshes,[])
})

test('公共表格先按当前原行重测高度再完整重算，原有尺寸与数据刷新不重测行高',async t=>{
  const f=await fixture(t),props=reactive({title:'物料明细',data:[{name:'控制板'}],columns:[{key:'name',title:'组件'}]})
  const mounted=f.mount(f.Table,props)
  await settle()
  assert.equal(typeof mounted.instance.refreshLayout,'function')
  assert.ok(f.recalculations.length>0)
  assert.ok(f.recalculations.every(value=>value===undefined),'挂载和原有宽度刷新不改变默认语义')
  assert.deepEqual(f.rowMeasurements,[])
  f.recalculations.length=0
  f.layoutCalls.length=0
  await mounted.instance.refreshLayout()
  assert.deepEqual(f.recalculations,[true])
  assert.deepEqual(f.layoutCalls,['rows','layout'])
  assert.equal(f.rowMeasurements.length,1)
  assert.equal(f.rowMeasurements[0],props.data,'行高重测接收当前真实行数组')
  assert.equal(f.rowMeasurements[0][0],props.data[0],'不能用克隆行代替 VXE 已持有的原行')
  f.recalculations.length=0
  f.observers[0].resize();await settle()
  assert.deepEqual(f.recalculations,[undefined])
  assert.equal(f.rowMeasurements.length,1,'普通尺寸回调不额外重测行高')
  f.recalculations.length=0
  props.data.push({name:'电源板'});await settle()
  assert.deepEqual(f.recalculations,[undefined])
  assert.equal(f.rowMeasurements.length,1,'数据数量变化仍沿用原来的普通刷新')
  // 数据源替换后，公开刷新必须测量最新原行，不能沿用首次挂载的数组快照。
  props.data=[{name:'新的当前行'}];await settle()
  f.recalculations.length=0;f.layoutCalls.length=0
  await mounted.instance.refreshLayout()
  assert.deepEqual(f.recalculations,[true])
  assert.deepEqual(f.layoutCalls,['rows','layout'])
  assert.equal(f.rowMeasurements.length,2)
  assert.equal(f.rowMeasurements[1],props.data)
  assert.equal(f.rowMeasurements[1][0],props.data[0])
  mounted.unmount();await settle()
  assert.ok(f.observers[0].disconnects>=1)
})
