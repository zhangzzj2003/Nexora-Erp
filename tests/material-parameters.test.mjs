import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { createPinia } from 'pinia'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'
import { hasMaterialDetails, materialChoiceSummary, materialParameterFacts } from '../src/renderer/src/utils/material-selection.ts'

const summary={id:1,sku:'PCB-1',name:'控制板',unit:'块'}
const categories=[{code:'EL',name:'电子类',children:[{code:'EL-PC',name:'电路板'}]}]
const spec=(field_id,name,status,value,unit='',historical=false)=>({field_id,name,status,value,unit,historical,
  source:'规格书 A',kind:typeof value==='boolean'?'boolean':'text',category_code:'EL-PC'})
const material={...summary,category_code:'EL-PC',specification:'FR-4',package:'双层裸板',brand:'示例品牌',manufacturer_part_number:'PCB-A',
  electrical_value:'DC 24V',tolerance:'±1%',rated_voltage:'',rated_power:'',temperature_range:'',compliance:'RoHS',notes:'装配前检查',
  spec_values:[spec(1,'板厚','filled','0','mm'),spec(2,'含铅','filled',false),spec(3,'阻抗','unknown',null),
    spec(4,'表面电阻','not_applicable',null),spec(5,'阻燃等级','pending',null),spec(6,'旧板宽','filled','60','mm',true)],
  spec_summary:'板厚：0mm；含铅：否；阻抗：未知',extra_attributes:[{name:'表面工艺',value:'沉金',unit:''}]}

// 编译并挂载真实只读展示及库存资料组件，仅替换按钮绘制；参数格式化仍走同一公共 helper。
async function fixture(t,inventory=false,initial={},nameView=false) {
  const files=['components/workspace/WorkspaceMaterialParameters.vue','components/workspace/InventoryMaterialFacts.vue','components/workspace/WorkspaceMaterialInfo.vue','components/workspace/WorkspaceMaterialName.vue']
  const modules=files.map(file=>{
    const filename=resolve('src/renderer/src',file)
    return [normalizePath(filename)+'.client.ts',compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,
      {id:file,inlineTemplate:true}).content]
  })
  const sources=new Map(modules)
  const server=await createServer({configFile:false,plugins:[{name:'material-parameters-client',enforce:'pre',
    resolveId(id){
      if(sources.has(id))return id
      if(id.endsWith('/WorkspaceMaterialParameters.vue'))return modules[0][0]
      if(id.endsWith('/WorkspaceMaterialInfo.vue'))return modules[2][0]
      if(id.endsWith('/WorkspaceMaterialName.vue'))return modules[3][0]
      if(id.endsWith('/AppButton.vue'))return '\0parameter-button'
      if(id.endsWith('/store/app-store'))return '\0parameter-store'
    },load(id){
      if(sources.has(id))return sources.get(id)
      if(id==='\0parameter-button')return `import {h} from 'vue';export default {props:['type','disabled','variant','size'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,type:p.type??'button',disabled:p.disabled},slots.default?.())}`
      if(id==='\0parameter-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];export const usePiniaAppStore=defineStore('parameter-facts',()=>({...createAppState(),loadLedgerMaterial(){calls.push('retry')}}))`
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:View}=await server.ssrLoadModule(modules[nameView?3:inventory?1:0][0])
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0parameter-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const props=reactive({material:structuredClone(material),categories,...initial})
  store.ledgerMaterialDetail=props.material;store.materialCategories=categories
  const element=tag=>({tag,children:[],props:{},text:'',parent:null}),root=element('root')
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
    insert(node,parent,anchor){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)
      const index=anchor?parent.children.indexOf(anchor):-1;parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent},
    remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null},
    setText(node,text){node.text=text},setElementText(node,text){node.text=text;node.children=[]},
    patchProp(node,key,old,value){node.props[key]=value},parentNode:node=>node.parent,
    nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null})
  const app=renderer.createApp({render:()=>h(View,inventory?{compact:props.compact??true}:props)}).use(pinia)
  app.mount(root);t.after(()=>app.unmount())
  const descendants=node=>[node,...node.children.flatMap(descendants)]
  const text=node=>[node.text,...node.children.map(text)].join(' ')
  return {props,store,calls,nodes:()=>descendants(root),text:()=>text(root),
    button:label=>descendants(root).find(node=>node.tag==='button'&&text(node).trim()===label),
    press(node){assert.ok(node);node.props.onClick({stopPropagation(){},preventDefault(){}})}}
}

test('参数事实复用状态格式，保留零值、否、历史及扩展属性并省略空字段与重复摘要',()=>{
  const before=JSON.stringify(material),facts=materialParameterFacts(material,categories)
  assert.deepEqual(facts.map(fact=>fact.key),['specification','package','brand','manufacturer_part_number','electrical_value','tolerance','compliance','notes',
    'spec:1','spec:2','spec:3','spec:4','spec:5','spec:6','extra:0'])
  assert.deepEqual(facts.filter(fact=>fact.key.startsWith('spec:')).map(({label,value})=>[label,value]),[
    ['板厚','0mm'],['含铅','否'],['阻抗','未知'],['表面电阻','不适用'],['阻燃等级','待确认'],['旧板宽（历史）','60mm']])
  assert.equal(facts.find(fact=>fact.key==='extra:0').value,'沉金')
  assert.equal(JSON.stringify(material),before,'只读摘要不能改变物料档案')
})

test('摘要或扩展属性单独提供仍可辨认，明确空详情与旧简要响应区分',()=>{
  assert.equal(hasMaterialDetails(summary),false)
  for(const detail of [{spec_summary:'板厚：1.6mm'},{extra_attributes:[{name:'工艺',value:'喷锡',unit:''}]},
    {spec_values:[]},{extra_attributes:[]},{specification:''}]) assert.equal(hasMaterialDetails({...summary,...detail}),true)
  assert.deepEqual(materialParameterFacts({...summary,spec_summary:'板厚：1.6mm'}),[{key:'spec_summary',label:'分类规格',value:'板厚：1.6mm'}])
  assert.deepEqual(materialParameterFacts({...summary,extra_attributes:[{name:'工艺',value:'喷锡',unit:''}]}),[{key:'extra:0',label:'工艺',value:'喷锡'}])
})

test('名称列默认与选料器共用一行摘要，点击查看才出现资料卡和当前档案标记',async t=>{
  const f=await fixture(t,false,{currentReference:true})
  const summaryNode=f.nodes().find(node=>node.props.class==='workspace-material-summary__text')
  assert.equal(summaryNode.text,materialChoiceSummary(material))
  assert.doesNotMatch(f.text(),/装配前检查|表面工艺|沉金|当前档案参数|PCB-1|控制板/)
  assert.equal(f.nodes().filter(node=>node.tag==='dl').length,0,'默认不渲染参数列表，避免撑高名称列')
  const toggle=f.button('查看资料')
  assert.equal(toggle.props['aria-expanded'],'false');assert.ok(toggle.props['aria-controls'])
  f.press(toggle);await nextTick()
  for(const value of ['当前档案参数','分类','电子类 / 电路板','规格型号','FR-4','封装','双层裸板','品牌','示例品牌','制造商料号','PCB-A','单位','块'])assert.ok(f.text().includes(value),value)
  assert.doesNotMatch(f.text(),/装配前检查|表面工艺|沉金/)
  assert.equal(f.button('收起资料').props['aria-expanded'],'true')
  assert.ok(f.nodes().some(node=>node.props.id===toggle.props['aria-controls']))
  assert.deepEqual(f.calls,[])
})

test('技术参数与长备注二次展开，保留零值否和历史，收起及换料清除展开状态',async t=>{
  const notes='这是需要按需阅读的长备注。'.repeat(15),f=await fixture(t,false,{material:{...structuredClone(material),notes}})
  const before=JSON.stringify(f.props.material)
  f.press(f.button('查看资料'));await nextTick()
  assert.equal(f.text().includes(notes),false)
  const toggle=f.button('展开详情')
  assert.equal(toggle.props['aria-expanded'],false)
  f.press(toggle);await nextTick()
  for(const value of [notes,'板厚','0mm','含铅','否','未知','不适用','待确认','旧板宽（历史）','60mm','表面工艺','沉金'])assert.ok(f.text().includes(value),value)
  assert.ok(f.nodes().some(node=>node.props.id===toggle.props['aria-controls']))
  assert.equal(f.button('收起详情').props['aria-expanded'],true)
  f.press(f.button('收起详情'));await nextTick();assert.equal(f.text().includes(notes),false)
  f.press(f.button('展开详情'));await nextTick()
  f.press(f.button('收起资料'));await nextTick()
  assert.equal(f.text().includes(notes),false);assert.ok(f.button('查看资料'))
  f.press(f.button('查看资料'));await nextTick();assert.equal(f.text().includes(notes),false)
  f.press(f.button('展开详情'));await nextTick()
  // 同一物料的授权资料刷新保留阅读状态，换料必须回到摘要。
  f.props.material={...f.props.material,brand:'新品牌'};await nextTick()
  assert.ok(f.text().includes(notes));assert.match(f.text(),/新品牌/)
  f.props.material={...f.props.material,id:2};await nextTick()
  assert.equal(f.text().includes(notes),false);assert.ok(f.button('查看资料'))
  assert.equal(JSON.stringify({...f.props.material,id:1,brand:material.brand}),before);assert.deepEqual(f.calls,[])
})

test('完整物料详情直接显示所有参数，只有备注或扩展属性的资料也能按需读取',async t=>{
  const f=await fixture(t,false,{compact:false})
  for(const value of ['FR-4','装配前检查','板厚','0mm','含铅','否','表面工艺','沉金'])assert.ok(f.text().includes(value),value)
  assert.equal(f.nodes().filter(node=>node.tag==='button').length,0)
  f.props.compact=true;f.props.material={...summary,notes:'只有备注的档案'};await nextTick()
  assert.doesNotMatch(f.text(),/只有备注的档案/)
  f.press(f.button('查看资料'));await nextTick();f.press(f.button('展开详情'));await nextTick()
  assert.match(f.text(),/只有备注的档案/)
  f.props.material={...summary,id:2,extra_attributes:[{name:'工艺',value:'喷锡',unit:''}]};await nextTick()
  f.press(f.button('查看资料'));await nextTick();f.press(f.button('展开详情'));await nextTick()
  assert.match(f.text(),/工艺|喷锡/)
  assert.deepEqual(f.calls,[])
})

test('旧服务和缺料显示资料不可用，空详情显示未填写，后续参数到达能响应更新并按文本展示',async t=>{
  const f=await fixture(t,false,{material:undefined,compact:false})
  assert.match(f.text(),/详细资料暂不可用/)
  f.props.material={...summary};await nextTick();assert.match(f.text(),/详细资料暂不可用/)
  f.props.material={...summary,specification:'',extra_attributes:[]};await nextTick()
  assert.match(f.text(),/参数未填写/);assert.doesNotMatch(f.text(),/详细资料暂不可用/)
  f.props.material={...summary,spec_summary:'电源：24V',extra_attributes:[{name:'刻字',value:'<img src=x onerror=alert(1)>',unit:''}]};await nextTick()
  assert.match(f.text(),/电源：24V|刻字/);assert.ok(f.text().includes('<img src=x onerror=alert(1)>'))
  assert.equal(f.nodes().some(node=>node.tag==='img'),false)
})

test('库存详情保留身份而将技术参数与扩展属性直接展示，加载及重试边界保持原行为',async t=>{
  const f=await fixture(t,true,{compact:false})
  for(const value of ['PCB-1','控制板','电子类 / 电路板','块','FR-4','板厚','0mm','含铅','否','表面工艺','沉金'])assert.ok(f.text().includes(value),value)
  assert.doesNotMatch(f.text(),/展开规格与更多资料|未填写/);assert.deepEqual(f.calls,[])
  f.store.ledgerMaterialLoading=true;await nextTick();assert.match(f.text(),/正在读取物料详情/)
  assert.doesNotMatch(f.text(),/沉金/)
  f.store.ledgerMaterialLoading=false;f.store.ledgerMaterialError='资料暂不可用';await nextTick()
  assert.match(f.text(),/资料暂不可用/);assert.doesNotMatch(f.text(),/沉金/)
  f.press(f.button('重新读取物料'));assert.deepEqual(f.calls,['retry'])
  f.store.connectionLost=true;await nextTick();assert.equal(f.button('重新读取物料').props.disabled,true)
})

// 名称组件必须锁住原单身份，不能因资料刷新或同名资料而覆盖名称、串料。
test('共享名称组件保留原单名称并核验真实物料 ID，换料收起且授权缓存可回退',async t=>{
  const f=await fixture(t,false,{name:'原单名称 · OLD-PCB',materialId:1},true)
  assert.match(f.text(),/原单名称 · OLD-PCB/);assert.doesNotMatch(f.text(),/控制板/)
  f.press(f.button('查看资料'));await nextTick()
  assert.match(f.text(),/FR-4/)
  f.props.material={...f.props.material,id:99,specification:'错误物料参数'};await nextTick()
  assert.match(f.text(),/原单名称 · OLD-PCB/);assert.doesNotMatch(f.text(),/错误物料参数/)
  assert.match(f.text(),/详细资料暂不可用/)
  f.props.cachedMaterials=new Map([[1,structuredClone(material)]]);await nextTick()
  assert.match(f.text(),/FR-4/)
  f.props.materialId=2;await nextTick()
  assert.doesNotMatch(f.text(),/FR-4/);assert.match(f.text(),/详细资料暂不可用/)
  f.props.material={...structuredClone(material),id:2};await nextTick()
  assert.ok(f.button('查看资料'))
  f.press(f.button('查看资料'));await nextTick();f.press(f.button('展开详情'));await nextTick()
  assert.match(f.text(),/沉金/)
  f.props.materialId=1;await nextTick();assert.ok(f.button('查看资料'))
  assert.deepEqual(f.calls,[])
})
