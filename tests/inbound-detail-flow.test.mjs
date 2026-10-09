import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
import {inboundFlowStoreSource} from './fixtures/inbound-flow-ui.mjs'

// 真实详情、审批控件和批次表参与测试，仅将依赖 DOM 的外壳换为可读取的 HTML。
async function environment(t){
 const server=await createServer({configFile:false,plugins:[{name:'inbound-flow-tests',enforce:'pre',
  transform(code,id){if(id.endsWith('.vue'))return code.replace(/(['"])naive-ui\1/g,"'virtual:flow-naive'")},
  resolveId(id,importer){
   if(id==='virtual:flow-naive')return '\0flow-naive'
   if(importer?.includes('/src/renderer/')&&id.endsWith('/store/app-store'))return '\0flow-store'
   for(const name of ['WorkspaceTable','AppButton','AppInput','WorkspaceSelect'])if(id.endsWith('/'+name+'.vue'))return '\0flow-'+name
  },load(id){
   if(id==='\0flow-store')return inboundFlowStoreSource
   if(id==='\0flow-naive')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}});export const NDatePicker=defineComponent({props:['formattedValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.formattedValue,disabled:p.disabled,'data-date':true})}});export const NDropdown=defineComponent({setup(p,{slots}){return()=>h('span',slots.default?.())}})`
   if(id==='\0flow-WorkspaceTable')return `import {defineComponent,h} from 'vue';export const tables=[];export default defineComponent({props:['data','columns','title'],setup(p,{slots}){tables.push({p,slots});return()=>h('div',[slots.heading?.(),slots.actions?.(),slots.filters?.(),h('table',{'aria-label':p.title},[h('thead',p.columns.map(c=>h('th',c.title))),h('tbody',p.data.map(row=>h('tr',p.columns.map(c=>h('td',slots['cell-'+c.key]?.({row}))))))])])}})`
   if(id==='\0flow-AppButton')return `import {defineComponent,h} from 'vue';export const buttons=[];export default defineComponent({props:['disabled','type'],setup(p,{slots,attrs}){return()=>{buttons.push({p,attrs,text:slots.default?.().map(v=>v.children).join('')});return h('button',{...attrs,type:p.type,disabled:p.disabled},slots.default?.())}}})`
   if(id==='\0flow-AppInput')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}})`
   if(id==='\0flow-WorkspaceSelect')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return()=>h('select')}})`
  }
 },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
 t.after(()=>server.close())
 return server
}

test('同一详情完成送审批准并衔接入库，失败保留详情与草稿，撤权和断线不能执行',async t=>{
 const server=await environment(t),pinia=createPinia()
 const {usePiniaAppStore,fixture}=await server.ssrLoadModule('\0flow-store'),store=usePiniaAppStore(pinia)
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue')
 let bindings
 const render=async()=>{
  const Open={...View,async setup(p,c){bindings=View.setup(p,c);await bindings.openInboundDetail(1);return bindings}}
  return renderToString(createSSRApp({render:()=>h(Open)}).use(pinia))
 }
 let html=await render()
 assert.equal((html.match(/data-modal=/g)??[]).length,1)
 assert.match(html,/其他入库详情/);assert.match(html,/>提交审批</)
 assert.ok(html.indexOf('审批进度')<html.indexOf('aria-label="基础信息"'))
 await store.actDocumentApproval('submit');await store.actDocumentApproval('approve')
 assert.equal(bindings.detailInboundId.value,1)
 assert.equal(store.otherInbounds[0].status,'draft')
 assert.equal(fixture.calls.filter(call=>call[0]==='post').length,0,'批准不能自动增加库存')
 html=await render()
 assert.equal((html.match(/data-modal=/g)??[]).length,1)
 assert.match(html,/审批已通过，请确认入库/)
 assert.ok(html.lastIndexOf('>确认入库<')>html.indexOf('document-footer'))
 assert.doesNotMatch(html,/审批记录 \/ 送审/)
 await bindings.handleInboundAction(1,'lots')
 assert.equal(bindings.lotDrafts.value.length,3)
 const draft=bindings.lotDrafts.value
 draft[0].lots[0].quantity='800';draft[0].lots[0].supplier_lot=' REAL '
 draft[1].lots.splice(0);draft[2].lots.splice(0)
 fixture.fail=true
 const before=JSON.stringify(draft)
 await bindings.confirmLotPost()
 assert.equal(bindings.activeInboundId.value,1)
 assert.equal(bindings.detailInboundId.value,1)
 assert.equal(JSON.stringify(draft),before)
 assert.deepEqual(fixture.calls.at(-1),['post',1,[{inbound_line_id:7,expected_received_quantity:'0',lots:[{quantity:'800',supplier_lot:'REAL',manufactured_on:null,expires_on:null}]}]])
 fixture.fail=false
 const count=fixture.calls.filter(call=>call[0]==='post').length
 store.connectionLost=true;await bindings.confirmLotPost();store.connectionLost=false
 store.user.permissions=[];await bindings.confirmLotPost()
 assert.equal(fixture.calls.filter(call=>call[0]==='post').length,count)
 store.user.permissions=['other_inbound.post']
 await bindings.confirmLotPost()
 assert.equal(bindings.activeInboundId.value,0)
 assert.equal(bindings.detailInboundId.value,1)
 assert.equal(store.otherInbounds[0].status,'partially_posted')
 assert.equal(store.otherInbounds[0].lines[0].remaining_quantity,'200')
 assert.equal(store.documentApprovalRecord.business_status,'partially_posted')
 bindings.closeInboundDetail()
 assert.equal(store.documentApprovalTarget,null)
})

test('统一批次表保持物料身份与草稿引用，空行可恢复，拆分与禁用边界不串行',async t=>{
 const server=await environment(t)
 const {default:Table}=await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceInboundLotTable.vue')
 const first={id:7,sku:'A',name:'排针',unit:'条',expected:'0.3',lots:[{quantity:'0.1'},{quantity:'0.2'}]}
 const skipped={id:8,sku:'B',name:'接线端子',unit:'个',expected:'100',lots:[]}
 const lines=[first,skipped],adds=[],removes=[]
 const vnode=h(Table,{lines,onAdd:id=>adds.push(id),onRemove:(id,index)=>removes.push([id,index])})
 const html=await renderToString(createSSRApp({render:()=>vnode}))
 assert.equal((html.match(/<table/g)??[]).length,1)
 assert.equal((html.match(/<thead/g)??[]).length,1)
 assert.match(html,/本次不入库/)
 assert.doesNotMatch(html,/已分配|数量已核对|本次后待入库/)
 const {tables}=await server.ssrLoadModule('\0flow-WorkspaceTable'),table=tables.at(-1)
 const rows=table.p.data
 assert.equal(rows[0].part,first.lots[0]);assert.equal(rows[1].part,first.lots[1]);assert.equal(rows[2].part,null)
 table.slots['cell-quantity']({row:rows[1]})[0].props['onUpdate:modelValue']('0.199')
 assert.equal(first.lots[1].quantity,'0.199')
 const b=vnode.component.setupState
 b.add(skipped);b.remove(first,1)
 assert.deepEqual(adds,[8]);assert.deepEqual(removes,[[7,1]])
 vnode.component.props.disabled=true;b.add(skipped);b.remove(first,0)
 assert.deepEqual(adds,[8]);assert.deepEqual(removes,[[7,1]])
 vnode.component.props.disabled=false
 b.remove(skipped,0);b.remove(first,99)
 while(first.lots.length<20)first.lots.push({quantity:'0.001'})
 b.add(first);assert.deepEqual(adds,[8])
})
