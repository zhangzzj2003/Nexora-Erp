import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { test } from 'node:test'
import { createRenderer, h, markRaw, nextTick, reactive } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createServer, normalizePath } from 'vite'

const settle=async()=>{await nextTick();await new Promise(done=>setImmediate(done));await nextTick()}
const models=[1,2].map(id=>({id,code:`SERIES-${id}`,name:`系列${id}`,child_count:1}))
const product=(id,modelId,name)=>({id,model_id:modelId,kind:modelId===null?'semi_finished':'finished',
  configuration_name:'',material_id:100+id,material:{id:100+id,name,sku:`SKU-${id}`}})
const rows=[product(1,1,'A 系列整机'),product(2,2,'B 系列整机'),product(3,null,'PCB 半成品')]

// 保留真实树模板及响应式状态，只替换控件绘制；原生按钮和导航节点支持持续点击、滚动及追加。
async function fixture(t,extra={}) {
  const filename=resolve('src/renderer/src/views/workspace/catalog/ProductTreeSidebar.vue')
  // 自定义渲染器没有浏览器样式系统；保留 Vue 过渡生命周期，CSS 中间帧另由浏览器验收。
  const content=compileScript(parse(readFileSync(filename,'utf8'),{filename}).descriptor,{id:'product-tree-navigation',inlineTemplate:true}).content
    .replace('Transition as _Transition','BaseTransition as _Transition')
  const moduleId=normalizePath(filename)+'.client.ts'
  const server=await createServer({configFile:false,plugins:[{name:'product-tree-navigation',enforce:'pre',resolveId(id){
    if(id===moduleId)return id
    if(id.startsWith('~icons/'))return '\0tree-navigation-icon'
    for(const [name,key] of [['AppButton','button'],['AppInput','input'],['WorkspaceSelect','select']])
      if(id.endsWith('/'+name+'.vue'))return '\0tree-navigation-'+key
  },load(id){
    if(id===moduleId)return content
    // 不在行为测试里复制图标实现，仍保留真实按钮的可访问名称及事件边界。
    if(id==='\0tree-navigation-icon')return `import {h} from 'vue';export default {render:()=>h('svg',{'aria-hidden':'true'})}`
    if(id==='\0tree-navigation-button')return `import {h} from 'vue';export default {props:['disabled','type'],setup:(p,{attrs,slots})=>()=>h('button',{...attrs,disabled:p.disabled,type:p.type},slots.default?.())}`
    if(id==='\0tree-navigation-input')return `import {h} from 'vue';export default {props:['modelValue','disabled'],setup:(p,{attrs})=>()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}`
    if(id==='\0tree-navigation-select')return `import {h} from 'vue';export default {props:['modelValue','options','disabled'],setup:(p,{attrs})=>()=>h('select',{...attrs,disabled:p.disabled},p.options.map(row=>h('option',{value:row.value},row.label)))}`
  }}],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Tree}=await server.ssrLoadModule(moduleId)
  const previous=globalThis.ResizeObserver,observers=[]
  globalThis.ResizeObserver=class {
    constructor(callback){this.callback=callback;this.targets=[];this.disconnected=false;observers.push(this)}
    observe(target){this.targets.push(target)}
    disconnect(){this.disconnected=true;this.targets=[]}
    resize(){this.callback([],this)}
  }
  t.after(()=>{if(previous===undefined)delete globalThis.ResizeObserver;else globalThis.ResizeObserver=previous})
  const all=node=>[node,...node.children.flatMap(all)]
  const element=tag=>markRaw({tag,children:[],props:{},text:'',parent:null,scrollTop:0,clientHeight:400,scrollHeight:1000})
  const root=element('root')
  const renderer=createRenderer({createElement:element,createText:text=>({...element('#text'),text}),createComment:()=>element('#comment'),
    insert(node,parent,anchor){
      if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1)
      const index=anchor?parent.children.indexOf(anchor):-1
      parent.children.splice(index<0?parent.children.length:index,0,node);node.parent=parent
    },remove(node){if(node.parent)node.parent.children.splice(node.parent.children.indexOf(node),1);node.parent=null},
    setText(node,text){node.text=text},setElementText(node,text){node.text=text;node.children=[]},
    patchProp(node,key,old,value){node.props[key]=value},parentNode:node=>node.parent,
    nextSibling:node=>node.parent?.children[node.parent.children.indexOf(node)+1]??null})
  const props=reactive({models:structuredClone(models),rows:structuredClone(rows),page:{items:structuredClone(rows),page:1,page_size:20,total:60},
    query:{query:'',kind:null,model_id:null,page:1,page_size:20},activeSeriesId:2,revealSeriesKey:0,
    selectedId:2,selected:structuredClone(rows[1]),loading:false,error:'',loadingMore:false,moreError:'',busy:false,disconnected:false,canManage:true,...extra})
  const events=[]
  const app=renderer.createApp({render:()=>h(Tree,{...props,
    onSeries:id=>{events.push(['series',id]);props.activeSeriesId=id},
    onSelect:id=>{events.push(['select',id]);props.selectedId=id;props.selected=props.rows.find(row=>row.id===id)??null},
    onLoadMore:()=>events.push(['more']),onNewModel:()=>events.push(['newModel']),onNewSeries:()=>events.push(['newSeries']),
    onEdit:id=>events.push(['edit',id]),onDelete:model=>events.push(['delete',model.id]),onReset:()=>events.push(['reset']),onRetry:()=>events.push(['retry'])})})
  app.mount(root);t.after(()=>app.unmount());await settle()
  const text=node=>[node.text,...node.children.map(text)].join('')
  const nodes=()=>all(root)
  const button=label=>nodes().find(node=>node.tag==='button'&&(text(node).includes(label)||String(node.props['aria-label']??'').includes(label)))
  const click=node=>{assert.ok(node,'目标按钮必须实际挂载');for(const handler of [node.props.onClick].flat())handler()}
  const nav=()=>nodes().find(node=>node.tag==='nav')
  const scroll=top=>{const node=nav();node.scrollTop=top;node.props.onScrollPassive({currentTarget:node})}
  return {props,events,observers,nodes,button,click,nav,scroll,nodeText:text,text:()=>text(root)}
}

test('主项互斥展开，未归组同样参与，收起不改变查询和右侧产品',async t=>{
  const f=await fixture(t,{models:[{...models[0],child_count:37},models[1]]}),query=JSON.stringify(f.props.query)
  assert.equal(f.button('A 系列整机'),undefined);assert.ok(f.button('B 系列整机'));assert.equal(f.button('PCB 半成品'),undefined)
  // 系列行不再绘制数量徽标，完整计数仍随原系列资料传入删除确认。
  assert.doesNotMatch(f.nodeText(f.button('系列1')),/37/)
  assert.equal(f.nodes().some(node=>node.props['aria-label']==='37 个子机型'),false)
  assert.match(f.text(),/60 个子机型/,'目录顶部仍显示完整查询总数')
  const remove=f.button('删除产品系列 系列1')
  assert.ok(remove,'图标按钮仍提供明确的可访问名称')
  assert.equal(remove.props['aria-label'],'删除产品系列 系列1')
  assert.match(remove.props.title,/删除/)
  assert.equal(f.nodeText(remove),'','图标删除入口使用可访问名，避免重新混入占位文字')
  assert.equal(remove.props.tone,'error');assert.equal(remove.props.variant,'plain')
  f.click(remove);await settle()
  assert.deepEqual(f.events,[['delete',1]])
  assert.equal(f.button('系列1').props['aria-expanded'],false,'删除入口不能展开所属系列')
  assert.ok(f.button('B 系列整机'))
  f.events.length=0
  f.click(f.button('系列1'));await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],true)
  assert.ok(f.button('A 系列整机'))
  assert.equal(f.button('B 系列整机'),undefined);assert.equal(f.button('PCB 半成品'),undefined)
  assert.equal(f.button('系列2').props['aria-expanded'],false)
  assert.equal(f.props.selectedId,2)
  assert.equal(JSON.stringify(f.props.query),query)
  assert.deepEqual(f.events,[['series',1]])
  assert.equal(f.button('展开全部'),undefined)
  f.click(f.button('未归组产品 / 半成品'));await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],false)
  assert.equal(f.button('A 系列整机'),undefined);assert.ok(f.button('PCB 半成品'))
  assert.equal(f.props.activeSeriesId,null)
  f.click(f.button('未归组产品 / 半成品'));await settle()
  assert.equal(f.button('PCB 半成品'),undefined)
  assert.ok(f.nodes().filter(node=>node.props.class==='tree-series').every(node=>node.props['aria-expanded']===false))
  assert.equal(f.props.selectedId,2)
  assert.equal(JSON.stringify(f.props.query),query)
  assert.deepEqual(f.events,[['series',1],['series',null],['series',null]])
})

test('归组与未归组子机型隐藏产品编码，系列编码保留且仍按原产品编号选择',async t=>{
  const f=await fixture(t)
  // 检查真实列表节点，隐藏的只是展示文字，选择事件继续传产品 ID 而非名称或物料编号。
  assert.doesNotMatch(f.text(),/SKU-1|SKU-2|SKU-3/)
  assert.match(f.text(),/SERIES-1/);assert.match(f.text(),/SERIES-2/)
  f.click(f.button('系列1'));await settle()
  assert.ok(f.button('A 系列整机'))
  f.click(f.button('A 系列整机'));await settle()
  assert.equal(f.props.selectedId,1)
  assert.equal(f.button('A 系列整机').props['aria-pressed'],true)
  f.click(f.button('未归组产品 / 半成品'));await settle()
  f.click(f.button('PCB 半成品'));await settle()
  assert.equal(f.props.selectedId,3)
  assert.equal(f.button('PCB 半成品').props['aria-pressed'],true)
  assert.deepEqual(f.events,[['series',1],['select',1],['series',null],['select',3]])
  assert.doesNotMatch(f.text(),/SKU-1|SKU-2|SKU-3/)
})

test('翻页追加不推翻手动折叠，选中不同机型或显式定位才展开祖先',async t=>{
  const f=await fixture(t)
  f.click(f.button('系列1'));await settle()
  f.click(f.button('系列1'));await settle()
  const fresh=product(4,1,'A 新追加机型')
  f.props.rows=[...f.props.rows,fresh];f.props.page={items:[fresh],page:2,page_size:20,total:60};await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],false)
  assert.equal(f.button('A 新追加机型'),undefined)
  assert.equal(f.button('PCB 半成品'),undefined)
  f.props.selectedId=4;f.props.selected=fresh;await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],true)
  assert.equal(f.button('系列2').props['aria-expanded'],false)
  assert.ok(f.button('A 新追加机型'))
  assert.equal(f.button('A 新追加机型').props['aria-pressed'],true)
  f.click(f.button('系列1'));await settle()
  assert.equal(f.button('A 新追加机型'),undefined)
  // 同 ID 的详情重读会短暂变空；这不是用户选择新机型，不能把手动收起的祖先又打开。
  f.props.selected=null;await settle()
  f.props.selected={...fresh};await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],false)
  assert.equal(f.button('A 新追加机型'),undefined)
  f.props.revealSeriesKey++;await settle()
  assert.equal(f.button('系列1').props['aria-expanded'],true)
  assert.ok(f.button('A 新追加机型'))
  f.click(f.button('系列2'));await settle()
  const moved={...fresh,model_id:2}
  f.props.rows=f.props.rows.map(row=>row.id===moved.id?moved:row);f.props.selected=moved;await settle()
  assert.equal(f.button('系列2').props['aria-expanded'],true,'同一产品真实改归属后应展开新祖先')
  assert.equal(f.button('系列1').props['aria-expanded'],false)
  assert.ok(f.button('A 新追加机型'))
})

test('收起压低目录高度不自动追页，上移夹紧不算下滚，用户下滚和加载按钮仍可继续',async t=>{
  const f=await fixture(t)
  f.scroll(300)
  f.click(f.button('系列2'));await settle()
  f.nav().scrollHeight=450
  f.scroll(50)
  f.observers[0].resize();await settle()
  assert.equal(f.events.filter(([event])=>event==='more').length,0)
  const fresh=product(4,1,'折叠下的新机型')
  f.props.rows=[...f.props.rows,fresh];f.props.page={items:[fresh],page:2,page_size:20,total:60};await settle()
  assert.equal(f.events.filter(([event])=>event==='more').length,0)
  f.nav().scrollHeight=460;f.scroll(60);await settle()
  assert.equal(f.events.filter(([event])=>event==='more').length,1)
  f.scroll(60);await settle()
  assert.equal(f.events.filter(([event])=>event==='more').length,1,'相同位置的滚动事件不能重复追加')
  f.click(f.button('加载更多'));await settle()
  assert.equal(f.events.filter(([event])=>event==='more').length,2)
})

test('没有未归组机型时根节点仍常驻，区分未加载和真正无匹配',async t=>{
  const assigned=structuredClone(rows.slice(0,2)),f=await fixture(t,{rows:assigned,page:{items:assigned,page:1,page_size:20,total:60}})
  assert.ok(f.button('未归组产品 / 半成品'))
  f.click(f.button('未归组产品 / 半成品'));await settle()
  assert.match(f.text(),/子机型尚未加载，可继续加载目录/)
  f.props.page={items:assigned,page:1,page_size:20,total:2};await settle()
  assert.ok(f.button('未归组产品 / 半成品'))
  assert.match(f.text(),/暂无匹配的未归组子机型/)
  f.click(f.button('未归组产品 / 半成品'));await settle()
  assert.equal(f.button('未归组产品 / 半成品').props['aria-expanded'],false)
})

test('忙碌与断线阻断旧按钮事件，查看账号可展开但不能借旧维护按钮写入',async t=>{
  const f=await fixture(t),series=f.button('系列2'),child=f.button('B 系列整机'),create=f.button('新建子机型'),edit=f.button('编辑产品系列 系列1'),remove=f.button('删除'),more=f.button('加载更多')
  for(const field of ['busy','disconnected']){
    f.props[field]=true;await settle()
    assert.equal(f.button('系列1').props.disabled,true)
    for(const node of [series,child,create,edit,remove,more])f.click(node)
    await settle()
    assert.deepEqual(f.events,[])
    assert.equal(f.button('系列2').props['aria-expanded'],true)
    f.props[field]=false;await settle()
  }
  f.props.canManage=false;await settle()
  assert.equal(f.button('新建子机型'),undefined);assert.equal(f.button('删除'),undefined);assert.equal(f.button('编辑产品系列'),undefined)
  f.click(create);f.click(edit);f.click(remove);assert.deepEqual(f.events,[])
  f.click(f.button('系列2'));await settle()
  assert.equal(f.button('系列2').props['aria-expanded'],false)
  assert.deepEqual(f.events,[['series',2]])
})

// 编辑是系列自己的动作；不能复用整行点击，从而误折叠或选走右侧产品。
test('系列树项独立编辑入口保留身份、折叠和选择，底部不再重复提供管理入口',async t=>{
 const f=await fixture(t),before=JSON.stringify([f.props.query,f.props.selectedId,f.props.activeSeriesId])
 const edit=f.button('编辑产品系列 系列1')
 assert.ok(edit);assert.equal(edit.props.title,'编辑产品系列 系列1')
 assert.equal(edit.props['aria-label'],'编辑产品系列 系列1');assert.equal(f.nodeText(edit),'')
 assert.equal(f.button('系列管理'),undefined);assert.ok(f.button('纳入已有物料'))
 f.click(edit);await settle()
 assert.deepEqual(f.events,[['edit',1]])
 assert.equal(f.button('系列1').props['aria-expanded'],false)
 assert.equal(f.button('A 系列整机'),undefined);assert.ok(f.button('B 系列整机'));assert.equal(f.button('PCB 半成品'),undefined)
 assert.equal(JSON.stringify([f.props.query,f.props.selectedId,f.props.activeSeriesId]),before)
 // 系列已从目录移除后，保留的旧图标事件也不能发送失效身份。
 f.props.models=f.props.models.filter(row=>row.id!==1);await settle()
 f.click(edit);assert.deepEqual(f.events,[['edit',1]])
 assert.equal(f.button('编辑产品系列 未归组'),undefined)
})

test('正常末页不再显示完成提示及空状态容器，真实目录数量变化仍可刷新',async t=>{
 const complete=structuredClone(rows),f=await fixture(t,{rows:complete,page:{items:complete,page:1,page_size:20,total:3}})
 assert.doesNotMatch(f.text(),/已显示全部|目录有更新/)
 assert.equal(f.nodes().some(node=>node.props.class==='tree-load-state'),false)
 assert.match(f.text(),/3 个子机型/,'顶部总数仍作为目录概览保留')
 f.props.page={...f.props.page,total:4};await settle()
 assert.match(f.text(),/已加载 3 个子机型，目录有更新/);assert.ok(f.button('刷新目录'))
 f.click(f.button('刷新目录'));assert.deepEqual(f.events,[['retry']])
 f.props.page={...f.props.page,total:3};await settle()
 assert.equal(f.nodes().some(node=>node.props.class==='tree-load-state'),false)
 f.props.rows=[];f.props.page={...f.props.page,items:[],total:0};f.props.selected=null;f.props.selectedId=0;await settle()
 assert.equal(f.nodes().some(node=>node.props.class==='tree-load-state'),false)
 assert.doesNotMatch(f.text(),/已显示全部|目录有更新/)
})

// 显式定位和目录更新同样不能绕过单项展开，null 与全部收起必须分开处理。
test('显式定位未归组与删除当前系列始终只保留一个或零个展开主项',async t=>{
 const f=await fixture(t)
 f.props.activeSeriesId=null;f.props.revealSeriesKey++;await settle()
 assert.equal(f.button('系列2').props['aria-expanded'],false)
 assert.equal(f.button('未归组产品 / 半成品').props['aria-expanded'],true)
 f.props.models=[...f.props.models,{id:4,code:'NEW',name:'新系列',child_count:0}];await settle()
 assert.equal(f.button('新系列').props['aria-expanded'],false,'新增目录节点不能默认展开')
 f.click(f.button('新系列'));await settle()
 assert.equal(f.button('未归组产品 / 半成品').props['aria-expanded'],false)
 assert.equal(f.button('新系列').props['aria-expanded'],true)
 f.props.models=f.props.models.filter(row=>row.id!==4);await settle()
 assert.ok(f.nodes().filter(node=>node.props.class==='tree-series').every(node=>node.props['aria-expanded']===false))
 assert.equal(f.props.selectedId,2,'删除目录节点不擅自更改当前产品')
})

test('收起后拒绝残留子项点击，快速切换后只展开最终主项',async t=>{
 const f=await fixture(t),oldChild=f.button('B 系列整机')
 f.click(f.button('系列1'));await settle()
 f.click(oldChild);await settle()
 assert.deepEqual(f.events,[['series',1]],'收起中的旧按钮不能抢走右侧产品')
 for(const label of ['系列2','未归组产品 / 半成品','系列1','系列1','系列2']){
  f.click(f.button(label));await settle()
 }
 assert.equal(f.button('系列2').props['aria-expanded'],true)
 assert.equal(f.button('系列1').props['aria-expanded'],false)
 assert.equal(f.button('未归组产品 / 半成品').props['aria-expanded'],false)
 assert.ok(f.button('B 系列整机'))
 assert.equal(f.button('A 系列整机'),undefined)
 assert.equal(f.button('PCB 半成品'),undefined)
})
