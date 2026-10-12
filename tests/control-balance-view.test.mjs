import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,createRenderer,h,nextTick,reactive,ssrContextKey} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

async function fixture(t){
  const server=await createServer({configFile:false,plugins:[{
    name:'control-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/ControlBalanceTransfersView.vue'))return code.replaceAll("'naive-ui'","'virtual:control-modal'")},
    resolveId(id,importer){
      if(id==='virtual:control-modal')return '\0control-modal'
      if((importer?.includes('/ControlBalanceTransfersView.vue')||importer?.includes('/ControlFundsSelector.vue'))&&id.endsWith('/store/app-store'))return '\0control-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0control-table'
      if(id.endsWith('/AppButton.vue'))return '\0control-button'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0control-select'
      if(['AuxiliarySelector.vue','DocumentApprovalDialog.vue','AppInput.vue','AppCollapseItem.vue'].some(file=>id.endsWith('/'+file)))return '\0control-stub'
    },load(id){
      if(id==='\0control-stub')return 'export default {render:()=>null}'
      if(id==='\0control-modal')return `import {defineComponent,h} from 'vue';export const NDatePicker={render:()=>null};export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}});export const NCollapse=defineComponent({setup(p,{slots}){return()=>h('section',slots.default?.())}})`
      if(id==='\0control-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['title','data','columns','loading'],setup(p,{slots}){return()=>h('section',{'aria-busy':!!p.loading},[h('h2',p.title),slots.filters?.(),...(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row})??String(row[c.key]??''))),!p.loading&&!p.data?.length?slots.empty?.():null])}})`
      if(id==='\0control-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0control-select')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled','modelValue','options'],setup(p){return()=>h('select',{disabled:p.disabled},p.options?.map(item=>h('option',{value:item.value,selected:item.value===p.modelValue,disabled:item.disabled},item.label)))}})`
      if(id==='\0control-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];export let saves=false;export const allowSave=()=>{saves=true};export const pending=[];
        export const usePiniaAppStore=defineStore('control-view',()=>{const state=createAppState();const write=name=>async(...input)=>{calls.push([name,...input]);return saves};return {...state,
        can:code=>state.user.value?.permissions.includes(code),openDocumentApproval:async()=>{},loadControlBalances:async()=>true,
        loadControlBalanceDetail:async()=>true,closeControlBalanceDetail:()=>{},queryControlBalances:async()=>true,
        loadControlBalanceJournal:async()=>true,closeControlBalanceJournal:()=>{},
        createControlBalanceTransfer:write('create'),generateControlBalanceJournal:write('generate'),reverseControlBalanceTransfer:write('reverse'),
        cancelControlBalanceTransfer:write('cancel'),postControlBalanceJournal:write('post'),cancelControlBalanceJournal:write('cancelJournal'),
        loadControlFundsOptions:query=>new Promise((resolve,reject)=>pending.push({query,resolve,reject}))}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close());const api=await server.ssrLoadModule('\0control-store'),pinia=createPinia(),store=api.usePiniaAppStore(pinia)
  store.user={id:1,roles:['finance'],permissions:['control_transfer.view','control_transfer.create','control_transfer.post','control_transfer.reverse','journal.create','journal.view','journal.post','journal.cancel']}
  return {server,pinia,store,...api}
}
const group=()=>({kind:'receivable',source_type:'historical',source_id:1,party_id:2,party_name:'客户甲',reference:'OLD-1',account_id:4,
  auxiliary:[{kind:'customer',id:2,name:'客户甲'},{kind:'project',id:3,name:'项目甲'}],outstanding_amount:'20.01',fingerprint:'a'.repeat(64),evidence:[],blockers:[]})
const record=()=>({id:1,document_no:'CBT-20261009-000001',kind:'receivable',operation:'reclassify',party_id:2,currency:'CNY',business_date:'2026-10-09',
  from_scope:group(),to_scope:{...group(),account_id:5},evidence:{source:group(),target:{...group(),account_id:5}},amount:'2.00',reference:'R',reason:'核对原单',
  status:'draft',version:1,reverses_id:null,reversal_id:null,journal_id:null,journal_status:null,approval:{status:'submitted',version:2}})

test('真实转账页面限定来源与控制科目，分别展示双重批准并保留失败输入',async t=>{
  const {server,pinia,store,calls,allowSave}=await fixture(t),{default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/ControlBalanceTransfersView.vue')
  const source=group();store.controlBalanceOptions={currency:'CNY',origins:[{...source,groups:[source,{...source,party_id:9}]}],
    accounts:[{id:4,code:'AR',name:'应收'},{id:5,code:'AR2',name:'其他应收'},{id:6,code:'AP',name:'应付'}],control_accounts:[{kind:'receivable',account_id:4},{kind:'receivable',account_id:5}],auxiliary_items:[],auxiliary_policies:[]}
  store.controlBalanceTransfers=[record()]
  let bindings,viewMode='records';const Real={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.mode.value=viewMode;return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real)}).use(pinia))
  assert.doesNotMatch(await render(),/>生成固定凭证<|>取消草稿<|>过账凭证并生效转账</)
  store.controlBalanceTransfers=[{...record(),approval:{status:'approved',version:3}}];assert.match(await render(),/>生成固定凭证</)
  bindings.start();bindings.form.value.source=bindings.sourceOptions.value[0].value;bindings.form.value.account_id=5
  Object.assign(bindings.form.value,{amount:'2',reference:'R-KEEP',reason:'保留失败输入'});assert.equal(bindings.limit.value,2001n)
  assert.deepEqual(bindings.accountOptions.value.map(row=>row.value),[4,5]);await bindings.save()
  assert.equal(bindings.editing.value,true);assert.equal(bindings.form.value.reference,'R-KEEP');assert.equal(calls.at(-1)[1].to_scope.account_id,5)
  allowSave();await bindings.save();assert.equal(bindings.editing.value,false)
  const row={...record(),journal_id:9,journal_status:'approved',approval:{status:'approved',version:3}};store.controlBalanceTransfers=[row]
  store.controlBalanceJournal={id:9,status:'approved',version:2,approval:{status:'approved',version:3},lines:[]}
  bindings.showJournal.value=true;bindings.ask(row,'post');bindings.commandReason.value='过账核对'
  store.controlBalanceJournal.approval.version=4;await bindings.confirm();assert.equal(calls.filter(call=>call[0]==='post').length,0)
  assert.match(store.error,/凭证审批已变化/)
  store.controlBalanceTransfers=[{...row,approval:{status:'draft',version:4}}];assert.equal(bindings.available(store.controlBalanceTransfers[0],'post'),false)
  store.user.permissions=['control_transfer.view'];assert.doesNotMatch(await render(),/>新增余额转账<|>生成固定凭证<|>建立反向转账</)
  viewMode='balances';store.controlBalanceReportLoading=true
  const loading=await render();assert.match(loading,/<p role="status">正在核对截止日组合…<\/p>/)
  assert.match(loading,/<section[^>]*aria-busy="true"/);assert.doesNotMatch(loading,/选择截止日并核对后/)
  assert.doesNotMatch(loading,/<h2>截止日完整组合余额<\/h2>.*?min-table-width="1200"/)
  assert.match(loading,/<button[^>]*disabled[^>]*>核对截止日组合<\/button>/)
  store.controlBalanceReportLoading=false;assert.match(await render(),/选择截止日并核对后/)
})

// 用无 DOM 渲染器挂载实际选择器，保留真实 watcher、事件和卸载行为。
const renderer=createRenderer({createElement:tag=>({tag,children:[]}),createText:text=>({text}),createComment:text=>({text}),
  setText:(node,text)=>{node.text=text},setElementText:(node,text)=>{node.text=text},parentNode:node=>node.parent,
  nextSibling:()=>null,patchProp:(node,key,old,value)=>{node[key]=value},insert:(node,parent)=>{node.parent=parent;parent.children.push(node)},remove:()=>{}})
const flush=async()=>{await Promise.resolve();await Promise.resolve();await nextTick()}
test('真实资金选择器按组合符号选收付款，必须显式选择且丢弃旧原单响应',async t=>{
  const {server,pinia,store,pending}=await fixture(t),{default:Selector}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/ControlFundsSelector.vue')
  const query=reactive({kind:'receivable',source_type:'historical',source_id:1}),events=[];let bindings
  const Real={...Selector,render:()=>null,setup(p,ctx){bindings=Selector.setup(p,ctx);return bindings}}
  const app=renderer.createApp({render:()=>h(Real,{query,action:'settlement','onUpdate:modelValue':value=>events.push(['value',value]),onReady:value=>events.push(['ready',value])})}).use(pinia)
  app.provide(ssrContextKey,{modules:new Set()});app.mount({children:[]});t.after(()=>app.unmount());assert.equal(pending.length,1)
  query.source_type='order';query.source_id=8;await flush();const current=pending.at(-1)
  const good={...group(),source_type:'order',source_id:8},credit={...good,account_id:5,outstanding_amount:'-5.00'}
  current.resolve({currency:'CNY',required:true,origin:{...good,outstanding_amount:'15.01',groups:[good,credit]}});await flush()
  assert.deepEqual(bindings.groups.value.map(row=>row.account_id),[4]);assert.equal(events.at(-1)[1],false)
  bindings.selected.value=bindings.choices.value[1].value;await flush();assert.equal(events.at(-1)[1],true)
  assert.deepEqual(events.filter(row=>row[0]==='value').at(-1)[1],{account_id:4,auxiliary:good.auxiliary.map(({kind,id})=>({kind,id})),fingerprint:good.fingerprint})
  pending[0].resolve({currency:'CNY',required:false,origin:null});await flush();assert.equal(bindings.options.value.required,true)
  store.connectionLost=true;await flush();assert.equal(events.at(-1)[1],false);assert.equal(bindings.options.value,null)
})
