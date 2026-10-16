import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'

const settle=async()=>{await nextTick();await new Promise(done=>setImmediate(done));await nextTick()}
const field=(id,code,name)=>({id,category_code:code,name,kind:'text',unit:'',options:[],allow_custom:false,required:false,enabled:true,sort_order:0,used:false,deleted:false})
const node=(code,name,enabled=true,extra={})=>({code,name,parent_code:code.includes('-')?code.split('-')[0]:null,
  enabled,deleted:false,used:false,version:2,template_version:1,notes:'',sort_order:0,material_count:0,fields:[],...extra})
const catalog=()=>[{...node('EL','电子类'),children:[node('EL-PC','控制板',true,{version:7,template_version:3,fields:[field(1,'EL-PC','层数')]}),node('EL-RE','电阻',false)]},
  {...node('PL','塑料类',false),children:[node('PL-HS','外壳',true,{fields:[field(2,'PL-HS','颜色')]})]}]

// 真实页面和表格行插槽持续挂载；只替换浮层、表格及基础控件绘制，保留所有页面入口与草稿逻辑。
async function fixture(t,{categories=catalog(),manage=true}={}) {
  const filename=resolve('src/renderer/src/views/workspace/catalog/MaterialCategoriesView.vue'),moduleId=normalizePath(filename)+'.client.ts'
  const source=compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,{id:'category-tree-view',inlineTemplate:true}).content
    .replace("from 'naive-ui'","from 'virtual:category-tree-naive'")
  const server=await createServer({configFile:false,plugins:[{name:'category-tree-view',enforce:'pre',resolveId(id){
    if(id===moduleId)return id
    if(id==='virtual:category-tree-naive')return '\0category-tree-naive'
    if(id.endsWith('/store/app-store'))return '\0category-tree-store'
    for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['AppButton','button'],['AppInput','input'],['WorkspaceSelect','select'],['AppCollapseItem','collapse']])
      if(id.endsWith('/'+name+'.vue'))return '\0category-tree-'+key
  },load(id){
    if(id===moduleId)return source
    if(id==='\0category-tree-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
      export const calls=[],behavior={};const copy=value=>JSON.parse(JSON.stringify(value));export const usePiniaAppStore=defineStore('category-tree-view',()=>{const s=createAppState();return {...s,
        can:key=>s.user.value?.permissions.includes(key)??false,cancelCatalogPreparation:()=>calls.push(['cancel']),
        reloadMaterialCategories:async()=>{calls.push(['reload']);return behavior.reload?await behavior.reload():true},
        saveMaterialCategory:async(data,editing)=>{calls.push(['saveCategory',copy(data),editing]);return false},
        saveMaterialSpecField:async data=>{calls.push(['saveField',copy(data)]);return false},removeMaterialCategory:async()=>false,
        loadMaterialCategoryChanges:async code=>{calls.push(['audit',code]);const current=s.materialCategories.value.flatMap(group=>[group,...group.children]).find(row=>row.code===code);
          s.materialCategoryChanges.value=[{id:1,category_code:code,action:'created',before:null,after:current,reason:'核对类别',changed_by_name:'管理员',created_at:'2026-10-16'}];return true},localTime:value=>value}})`
    if(id==='\0category-tree-modal')return `import {h} from 'vue';export default {props:['show','ready','originKey','title'],setup:(p,{slots})=>()=>p.show&&p.ready!==false?h('section',{'data-modal':p.originKey,'data-title':p.title},slots.default?.()):null}`
    if(id==='\0category-tree-table')return `import {h} from 'vue';export default {props:['title','description','data','columns','pagination'],setup:(p,{slots})=>()=>h('section',{'data-table':p.title,'data-paginated':String(p.pagination!==undefined)},[
      h('h2',p.title),p.description?h('p',p.description):null,slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...p.data.map(row=>h('article',{'data-code':row.code??String(row.id)},p.columns.map(column=>h('div',{'data-column':column.key},slots['cell-'+column.key]?.({row})??String(row[column.key]??''))))),!p.data.length?slots.empty?.():null])}`
    if(id==='\0category-tree-button')return `import {h} from 'vue';export default {props:['disabled','type'],setup:(p,{slots,attrs})=>()=>h('button',{...attrs,disabled:p.disabled,type:p.type},slots.default?.())}`
    if(id==='\0category-tree-input')return `import {h} from 'vue';export default {props:['modelValue','disabled','type'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled,type:p.type})}`
    if(id==='\0category-tree-select')return `import {h} from 'vue';export default {props:['modelValue','disabled','options'],setup:(p,{attrs})=>()=>h('select',{...attrs,value:p.modelValue,disabled:p.disabled},p.options.map(row=>h('option',{value:row.value},row.label)))}`
    if(id==='\0category-tree-collapse')return `import {h} from 'vue';export default {props:['title'],setup:(p,{slots})=>()=>h('section',[h('h4',p.title),slots.default?.()])}`
    if(id==='\0category-tree-naive')return `import {h} from 'vue';export const NCollapse={setup:(p,{slots})=>()=>h('section',slots.default?.())};export const NPopconfirm={setup:(p,{slots})=>()=>h('section',slots.trigger?.())};export const NSwitch={props:['value','disabled'],setup:(p,{attrs})=>()=>h('input',{...attrs,type:'checkbox',checked:p.value,disabled:p.disabled})}`
  }}],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:View}=await server.ssrLoadModule(moduleId)
  const {usePiniaAppStore,calls,behavior}=await server.ssrLoadModule('\0category-tree-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,permissions:manage?['inventory.view','catalog.manage']:['inventory.view']}
  store.server={id:'category-test',fingerprint:'test'};store.materialCategories=structuredClone(categories)
  const element=tag=>markRaw({tag,children:[],props:{},text:'',parent:null}),root=element('root')
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
    insert(item,parent,anchor){if(item.parent)item.parent.children.splice(item.parent.children.indexOf(item),1);const index=anchor?parent.children.indexOf(anchor):-1;parent.children.splice(index<0?parent.children.length:index,0,item);item.parent=parent},
    remove(item){if(item.parent)item.parent.children.splice(item.parent.children.indexOf(item),1);item.parent=null},setText(item,text){item.text=text},setElementText(item,text){item.text=text;item.children=[]},
    patchProp(item,key,old,value){item.props[key]=value},parentNode:item=>item.parent,nextSibling:item=>item.parent?.children[item.parent.children.indexOf(item)+1]??null})
  const app=renderer.createApp({render:()=>h(View)}).use(pinia);app.mount(root);t.after(()=>app.unmount());await settle()
  const descendants=item=>[item,...item.children.flatMap(descendants)],text=item=>[item.text,...item.children.map(text)].join('')
  const nodes=(within=root)=>descendants(within)
  const row=code=>nodes().find(item=>item.props['data-code']===code)
  const button=(label,within=root)=>nodes(within).find(item=>item.tag==='button'&&(text(item)===label || item.props['aria-label']===label))
  const press=item=>{assert.ok(item,'操作入口必须真实渲染');for(const handler of [item.props.onClick].flat())handler()}
  const control=label=>nodes().find(item=>['input','select'].includes(item.tag)&&item.props['aria-label']===label)
  const update=async(label,value)=>{const item=control(label);assert.ok(item);item.props['onUpdate:modelValue'](value);await settle()}
  const modal=key=>nodes().find(item=>item.props['data-modal']===`MaterialCategoriesView:${key}`)
  return {store,calls,behavior,nodes,row,button,press,update,modal,nodeText:text,text:()=>text(root)}
}

test('分类目录默认父子展开且无行分页，搜索临时展开命中祖先，清空恢复手动收起',async t=>{
  const f=await fixture(t)
  assert.deepEqual(f.nodes().filter(item=>item.props['data-code']).map(item=>item.props['data-code']),['EL','EL-PC','EL-RE','PL','PL-HS'])
  assert.equal(f.nodes().find(item=>item.props['data-table']==='物料类别').props['data-paginated'],'false')
  assert.doesNotMatch(f.text(),/查看子类规格模板/)
  f.press(f.button('收起电子类子类'));await settle()
  assert.equal(f.row('EL-PC'),undefined);assert.ok(f.row('PL-HS'))
  await f.update('搜索类别','控制板')
  assert.ok(f.row('EL'));assert.ok(f.row('EL-PC'));assert.equal(f.row('EL-RE'),undefined);assert.equal(f.row('PL'),undefined)
  assert.equal(f.button('收起电子类子类').props.disabled,true)
  assert.match(f.text(),/清空条件后恢复手动收起/)
  await f.update('搜索类别','')
  assert.equal(f.row('EL-PC'),undefined);assert.ok(f.row('PL-HS'))
})

test('启用筛选保留停用父类上下文，子类保留自身状态及父类限制，禁止向停用父类新增',async t=>{
  const f=await fixture(t)
  await f.update('筛选类别状态','enabled')
  assert.ok(f.row('PL'));assert.ok(f.row('PL-HS'));assert.equal(f.row('EL-RE'),undefined)
  assert.match(f.nodeText(f.row('PL')),/匹配子类所属大类/)
  assert.match(f.nodeText(f.row('PL-HS')),/启用.*所属大类已停用/)
  const add=f.button('新增子类',f.row('PL'))
  assert.equal(add.props.disabled,true);f.press(add);await settle()
  assert.equal(f.calls.some(([action])=>action==='reload'),false)
  f.press(f.button('规格字段',f.row('PL-HS')));await settle()
  assert.ok(f.nodes().some(item=>item.props['data-table']==='塑料类 / 外壳 · 规格模板 v1'))
})

test('子类行打开所属路径明确的规格面板，编辑使用类别版本，折叠换类和失败保留原规格草稿',async t=>{
  const f=await fixture(t)
  f.press(f.button('规格字段',f.row('EL-PC')));await settle()
  assert.ok(f.nodes().some(item=>item.props['data-table']==='电子类 / 控制板 · 规格模板 v3'))
  assert.match(f.text(),/所属子类：电子类 \/ 控制板（EL-PC）/)
  f.press(f.button('新增规格字段'));await settle()
  assert.equal(f.store.materialFieldDraft.code,'EL-PC');assert.equal(f.store.materialFieldDraft.version,7)
  assert.match(f.nodeText(f.modal('field')),/电子类 \/ 控制板/)
  f.store.materialFieldDraft.name='尚未保存的参数';f.store.materialFieldDraft.reason='根据图纸新增';await settle()
  const draft=JSON.stringify(f.store.materialFieldDraft)
  const form=f.nodes(f.modal('field')).find(item=>item.tag==='form')
  form.props.onSubmit({preventDefault(){}});await settle()
  assert.equal(f.store.materialFieldEditorOpen,true);assert.equal(JSON.stringify(f.store.materialFieldDraft),draft)
  f.press(f.button('关闭并保留草稿',f.modal('field')));await settle()
  f.press(f.button('规格字段',f.row('PL-HS')));await settle()
  f.press(f.button('收起电子类子类'));await settle()
  const reads=f.calls.filter(([action])=>action==='reload').length
  f.press(f.button('继续规格草稿'));await settle()
  assert.equal(JSON.stringify(f.store.materialFieldDraft),draft)
  assert.equal(f.calls.filter(([action])=>action==='reload').length,reads)
  assert.match(f.nodeText(f.modal('field')),/电子类 \/ 控制板/)
})

test('只读账号可展开目录、查看子类规格和审计，维护入口隐藏',async t=>{
  const f=await fixture(t,{manage:false})
  assert.equal(f.button('新增大类'),undefined);assert.equal(f.button('编辑',f.row('EL-PC')),undefined)
  f.press(f.button('收起电子类子类'));await settle();assert.equal(f.row('EL-PC'),undefined)
  f.press(f.button('展开电子类子类'));await settle()
  f.press(f.button('规格字段',f.row('EL-PC')));await settle()
  assert.ok(f.nodes().some(item=>item.props['data-table']==='电子类 / 控制板 · 规格模板 v3'))
  assert.equal(f.button('新增规格字段'),undefined)
  f.press(f.button('变更记录',f.row('EL-PC')));await settle()
  assert.deepEqual(f.calls.find(([action])=>action==='audit'),['audit','EL-PC'])
  assert.match(f.modal('audit').props['data-title'],/电子类 \/ 控制板/)
})

test('旧服务仍显示完整树，维护规格与审计不可通过迟到按钮事件绕过',async t=>{
  const f=await fixture(t,{categories:[{code:'OLD',name:'旧材料',children:[{code:'OLD-AA',name:'历史子类'}]}]})
  assert.ok(f.row('OLD'));assert.ok(f.row('OLD-AA'));assert.match(f.text(),/请升级 ERP 服务/)
  assert.equal(f.button('新增大类').props.disabled,true)
  for(const item of [f.button('新增大类'),f.button('编辑',f.row('OLD-AA')),f.button('规格字段',f.row('OLD-AA')),f.button('变更记录',f.row('OLD-AA'))]){
    assert.equal(item.props.disabled,true);f.press(item)
  }
  await settle()
  assert.equal(f.calls.some(([action])=>['reload','audit','saveCategory','saveField'].includes(action)),false)
  assert.equal(f.store.materialCategoryEditorOpen,false);assert.equal(f.store.materialFieldEditorOpen,false)
})

test('编辑入口重读后类别或字段被移除时不降级新增，并保留已有草稿',async t=>{
  const f=await fixture(t)
  f.store.materialCategoryDraft.name='原类别草稿'
  f.behavior.reload=async()=>{f.store.materialCategories=[{...catalog()[0],children:[]}];return true}
  f.press(f.button('编辑',f.row('EL-PC')));await settle()
  assert.equal(f.store.materialCategoryEditorOpen,false)
  assert.equal(f.store.materialCategoryDraft.name,'原类别草稿');assert.match(f.store.error,/类别资料已变化/)
  f.store.materialCategories=catalog();await settle()
  f.press(f.button('规格字段',f.row('EL-PC')));await settle()
  f.store.materialFieldDraft.name='原规格草稿'
  f.behavior.reload=async()=>{const next=catalog();next[0].children[0].fields=[];f.store.materialCategories=next;return true}
  const panel=f.nodes().find(item=>item.props['data-table']==='电子类 / 控制板 · 规格模板 v3')
  f.press(f.button('编辑',panel));await settle()
  assert.equal(f.store.materialFieldEditorOpen,false)
  assert.equal(f.store.materialFieldDraft.name,'原规格草稿');assert.match(f.store.error,/规格字段已变化/)
})
