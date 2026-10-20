import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'

// 真实产品弹窗和物料选择器参与响应式更新，仅替换依赖浏览器绘制的控件。
async function fixture(t) {
  // 选择器改为组合共享资料卡后，持续挂载测试也需编译真实子组件，不能混入 SSR 专用渲染函数。
  const files=['views/workspace/catalog/ProductEditor.vue','components/workspace/WorkspaceMaterialSelect.vue','components/workspace/WorkspaceMaterialInfo.vue']
  const modules=files.map(file=>{
    const filename=resolve('src/renderer/src',file)
    return [normalizePath(filename)+'.client.ts',compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,
      {id:file,inlineTemplate:true}).content]
  })
  const sources=new Map(modules)
  const server=await createServer({configFile:false,plugins:[{name:'product-material-summary',enforce:'pre',
    resolveId(id){
      if(sources.has(id))return id
      if(id.endsWith('/WorkspaceMaterialSelect.vue'))return modules[1][0]
      if(id.endsWith('/WorkspaceMaterialInfo.vue'))return modules[2][0]
      if(id.endsWith('/store/app-store'))return '\0summary-store'
      if(id.endsWith('/WorkspaceDocumentDialog.vue'))return '\0summary-dialog'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0summary-select'
      if(id.endsWith('/AppInput.vue')||id.endsWith('/AppButton.vue'))return '\0summary-control'
      if(id.endsWith('/ProductProfileFields.vue')||id.endsWith('/MaterialEditor.vue')||id.endsWith('/AppModal.vue'))return '\0summary-empty'
    },load(id){
      if(sources.has(id))return sources.get(id)
      if(id==='\0summary-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
        export const writes=[];export const usePiniaAppStore=defineStore('product-material-summary',()=>({...createAppState(),
          can:()=>true,saveProduct:async()=>{writes.push('save');return null}}))`
      if(id==='\0summary-dialog')return `import {h} from 'vue';export default {props:['show','busy','disabled'],setup:(p,{slots,emit})=>()=>p.show?h('form',{onSubmit:()=>emit('submit')},slots.basicInfo?.()):null}`
      if(id==='\0summary-select')return `import {h} from 'vue';export default {props:['modelValue','options','disabled','required'],setup:(p,{attrs})=>()=>h('select',{...attrs,disabled:p.disabled,required:p.required},p.options.map(o=>h('option',{value:o.value},o.label)))}`
      if(id==='\0summary-control')return `import {h} from 'vue';export default {props:['disabled','modelValue'],setup:(p,{slots,attrs})=>()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}`
      if(id==='\0summary-empty')return 'export default {render:()=>null}'
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,writes}=await server.ssrLoadModule('\0summary-store')
  const {default:Editor}=await server.ssrLoadModule(modules[0][0])
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.productForm={...store.productForm,mode:'existing',material_id:1,configuration_name:'长续航',reason:'保留说明'}
  store.productEditorOpen=true
  store.materials=[{id:1,sku:'PCB-1',name:'控制板',unit:'块',specification:'FR-4',package:'双层',brand:'示例品牌',manufacturer_part_number:'PCB-A'},
    {id:2,sku:'PCB-2',name:'电源板',unit:'块',specification:'DC 24 V'}]
  const element=tag=>({tag,children:[],props:{},text:'',parent:null}),root=element('root')
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
    insert(node,parent,anchor){
      if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)
      const index=anchor?parent.children.indexOf(anchor):-1
      parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent
    },remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null},
    setText(node,text){node.text=text},setElementText(node,text){node.text=text;node.children=[]},
    patchProp(node,key,old,value){node.props[key]=value},parentNode:node=>node.parent,
    nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null})
  let material,dialog
  const app=renderer.createApp({render:()=>h(Editor)}).use(pinia)
  app.mixin({created(){if(this.$options.__name==='WorkspaceMaterialSelect')material=this.$
    if(this.$options.props?.includes?.('show'))dialog=this.$}})
  // 真实物料选择器监听窗口缩放；内存渲染器提供事件宿主并在卸载后恢复。
  const previousWindow=globalThis.window
  globalThis.window=new EventTarget()
  t.after(()=>{app.unmount();globalThis.window=previousWindow})
  app.mount(root)
  const text=node=>[node.text??'',...node.children.map(text)].join(' ')
  return {store,writes,text:()=>text(root),get material(){return material},get dialog(){return dialog}}
}

test('纳入物料默认收缩为公共摘要，按需展开并在换料或重开时自动收起',async t=>{
  const f=await fixture(t)
  assert.equal(f.material.props.compact,true)
  assert.match(f.text(),/FR-4 · 双层 · 示例品牌 · PCB-A/)
  const before=JSON.stringify(f.store.productForm)
  f.material.emit('update:compact',false);await nextTick()
  assert.equal(f.material.props.compact,false)
  assert.equal(JSON.stringify(f.store.productForm),before)
  // 换料只更新选择编号，已填写的产品配置及说明不被展示状态覆盖。
  f.material.emit('update:modelValue',2);await nextTick()
  assert.equal(f.material.props.compact,true)
  assert.equal(f.store.productForm.material_id,2)
  assert.equal(f.store.productForm.configuration_name,'长续航')
  assert.equal(f.store.productForm.reason,'保留说明')
  f.material.emit('update:compact',false);await nextTick()
  f.store.productEditorOpen=false;await nextTick()
  f.store.productEditorOpen=true;await nextTick()
  assert.equal(f.material.props.compact,true)
})

test('资料收缩不改保存草稿，失败保留展开状态，忙碌及断线仍禁用公共选择器',async t=>{
  const f=await fixture(t)
  f.material.emit('update:compact',false);await nextTick()
  const before=JSON.stringify(f.store.productForm)
  f.dialog.emit('submit');await nextTick();await nextTick()
  assert.deepEqual(f.writes,['save'])
  assert.equal(f.store.productEditorOpen,true)
  assert.equal(f.material.props.compact,false)
  assert.equal(JSON.stringify(f.store.productForm),before)
  for(const key of ['busy','connectionLost']){
    f.store[key]=true;await nextTick()
    assert.equal(f.material.props.disabled,true)
    f.store[key]=false;await nextTick()
    assert.equal(f.material.props.disabled,false)
  }
})
