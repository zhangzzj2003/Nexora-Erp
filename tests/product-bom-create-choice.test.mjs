import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, createSSRApp, h, nextTick, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'

const source = (id, status='active') => ({id,product_material_id:id,product_name:`来源产品${id}`,product_sku:`MAT-${id}`,
  product_unit:'台',version:id,base_quantity:'1',status,lines:[{id,component_material_id:99,quantity:'2'}]})

// 真实选择弹窗与共享单据外壳参与渲染，只替换依赖浏览器的浮层、表格及基础控件绘制。
async function fixture(t, extra={}) {
  const modules=['views/workspace/catalog/ProductBomReuseDialog.vue','components/workspace/WorkspaceDocumentDialog.vue'].map(file=>{
    const filename=resolve('src/renderer/src',file)
    return [normalizePath(filename)+'.client.ts',compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,
      {id:file,inlineTemplate:true}).content]
  })
  const sources=new Map(modules)
  const server=await createServer({configFile:false,plugins:[{name:'product-bom-create-choice',enforce:'pre',
    resolveId(id) {
      if(sources.has(id))return id
      if(id.endsWith('/WorkspaceDocumentDialog.vue'))return modules[1][0]
      for(const [name,key] of [['AppModal','modal'],['WorkspaceTable','table'],['AppButton','button'],['AppInput','input']])
        if(id.endsWith('/'+name+'.vue'))return '\0bom-choice-'+key
    },load(id) {
      if(sources.has(id))return sources.get(id)
      if(id==='\0bom-choice-modal')return `import {h} from 'vue';export default {props:['show','title'],setup:(p,{slots})=>()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}`
      if(id==='\0bom-choice-table')return `import {h} from 'vue';export default {props:['data','columns'],setup:(p,{slots})=>()=>h('section',{'data-row-count':p.data.length},[slots.heading?.(),...p.data.map(row=>h('article',{'data-source':row.id},p.columns.map(column=>slots['cell-'+column.key]?.({row}))))])}`
      if(id==='\0bom-choice-button')return `import {h} from 'vue';export default {props:['disabled','type'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,disabled:p.disabled,type:p.type},slots.default?.())}`
      if(id==='\0bom-choice-input')return `import {h} from 'vue';export default {props:['modelValue'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue})}`
    }}],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Dialog}=await server.ssrLoadModule(modules[0][0])
  const props=reactive({show:true,sources:[source(1),source(2,'draft'),source(3,'retired'),source(4,'cancelled')],
    targetName:'NET-8890',busy:false,disconnected:false,...extra})
  const events=[]
  const dialog=()=>h(Dialog,{...props,onBlank:()=>events.push(['blank']),onChoose:bom=>events.push(['choose',bom]),
    'onUpdate:show':show=>events.push(['show',show])})
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
  const app=renderer.createApp({render:dialog});app.mount(root);t.after(()=>app.unmount())
  const text=node=>[node.text,...node.children.map(text)].join('')
  const nodes=node=>[node,...node.children.flatMap(nodes)]
  const button=label=>nodes(root).find(node=>node.tag==='button' && text(node)===label)
  const click=node=>{assert.ok(node,'目标按钮必须实际渲染');node.props.onClick()}
  return {props,events,root,text:()=>text(root),nodes:()=>nodes(root),button,click,
    html:()=>renderToString(createSSRApp({render:dialog}))}
}

test('新版本弹窗通过真实共享外壳展示空白创建与完整复用说明，旧复用入口兼容',async t=>{
  const f=await fixture(t)
  let html=await f.html()
  assert.match(html,/data-modal="选择要复用的 BOM"/)
  assert.doesNotMatch(html,/空白创建|从空白开始/)
  f.props.allowBlank=true;await nextTick();html=await f.html()
  for(const text of ['新建 BOM 版本','空白创建','NET-8890','原版本或其他产品','复制完整组成生成新草稿','原 BOM 版本保持不变'])
    assert.ok(html.includes(text),text)
  assert.match(html,/data-row-count="3"/)
  assert.doesNotMatch(html,/来源产品4/)
})

test('空白和草稿、启用、停用来源都通过按钮上报，来源内容不被选择动作修改',async t=>{
  const f=await fixture(t,{allowBlank:true}),before=JSON.stringify(f.props.sources)
  f.click(f.button('空白创建'))
  for(const node of f.nodes().filter(node=>node.tag==='button' && node.props.onClick &&
    node.children.some(child=>child.text==='复用到当前机型')))
    f.click(node)
  assert.deepEqual(f.events.map(([event,bom])=>[event,bom?.id]),[['blank',undefined],['choose',1],['choose',2],['choose',3]])
  assert.equal(JSON.stringify(f.props.sources),before)
})

test('忙碌、断线、关闭及关闭空白能力后，已保存的旧按钮事件也不能触发创建',async t=>{
  const f=await fixture(t,{allowBlank:true}),blank=f.button('空白创建'),choose=f.button('复用到当前机型'),cancel=f.button('取消')
  for(const key of ['busy','disconnected']) {
    f.props[key]=true;await nextTick()
    assert.equal(f.button('空白创建').props.disabled,true)
    assert.equal(f.button('复用到当前机型').props.disabled,true)
    f.click(blank);f.click(choose)
    assert.deepEqual(f.events,[])
    if(key==='busy'){f.click(cancel);assert.deepEqual(f.events,[])}
    f.props[key]=false;await nextTick()
  }
  f.props.allowBlank=false;await nextTick();f.click(blank)
  assert.deepEqual(f.events,[])
  f.props.show=false;await nextTick();f.click(blank);f.click(choose)
  assert.deepEqual(f.events,[])
  f.props.show=true;f.props.disconnected=true;await nextTick()
  f.click(f.button('取消'))
  assert.deepEqual(f.events,[['show',false]])
})

test('来源被取消或移除后旧行点击失效，替换快照后选择最新来源对象',async t=>{
  const f=await fixture(t,{allowBlank:true}),old=f.button('复用到当前机型')
  f.props.sources=[source(1,'cancelled')];await nextTick();f.click(old)
  assert.deepEqual(f.events,[])
  f.props.sources=[];await nextTick();f.click(old)
  assert.deepEqual(f.events,[])
  f.props.sources=[{...source(1),note:'最新快照'}];await nextTick();f.click(old)
  assert.equal(f.events.length,1)
  assert.equal(f.events[0][1],f.props.sources[0])
  assert.equal(f.events[0][1].note,'最新快照')
})

test('无可读来源仍可空白创建，搜索无匹配不误报没有任何 BOM',async t=>{
  const f=await fixture(t,{allowBlank:true,sources:[]})
  assert.match(await f.html(),/暂无可复用的 BOM，可选择空白创建/)
  assert.equal(f.nodes().filter(node=>node.tag==='article').length,0)
  f.click(f.button('空白创建'));assert.deepEqual(f.events,[['blank']])
  f.props.sources=[source(1)];await nextTick()
  f.nodes().find(node=>node.tag==='input').props['onUpdate:modelValue']('不匹配来源');await nextTick()
  assert.match(f.text(),/未找到匹配的可复用版本，请调整搜索条件/)
  assert.equal(f.nodes().filter(node=>node.tag==='article').length,0)
  f.click(f.button('空白创建'));assert.equal(f.events.length,2)
})
