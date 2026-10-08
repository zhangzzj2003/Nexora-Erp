import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h,nextTick} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

test('真实跨原单订单页面限定完整归属，保留失败输入并拒绝过期批准',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'subledger-order-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/SubledgerOrderSettlements.vue'))return code.replaceAll("'naive-ui'","'virtual:bridge-modal'")},
    resolveId(id,importer){
      if(id==='virtual:bridge-modal')return '\0bridge-modal'
      if(importer?.includes('/SubledgerOrderSettlements.vue')&&id.endsWith('/store/app-store'))return '\0bridge-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0bridge-table'
      if(id.endsWith('/AppButton.vue'))return '\0bridge-button'
      if(id.endsWith('/AppCollapseItem.vue'))return '\0bridge-collapse'
      if(id.endsWith('/WorkspaceSelect.vue')||id.endsWith('/AppInput.vue'))return '\0bridge-stub'
    },load(id){
      if(id==='\0bridge-stub')return 'export default {render:()=>null}'
      if(id==='\0bridge-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}});export const NCollapse=defineComponent({setup(p,{slots}){return()=>h('section',slots.default?.())}})`
      if(id==='\0bridge-collapse')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['title'],setup(p,{slots}){return()=>h('section',[h('p',p.title),slots.default?.()])}})`
      if(id==='\0bridge-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0bridge-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0bridge-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];export let saves=false;export const allowSave=()=>{saves=true};
        export const usePiniaAppStore=defineStore('bridge-view',()=>{const state=createAppState();return {...state,
        can:code=>state.user.value?.permissions.includes(code),openDocumentApproval:async()=>{},loadSubledgerOrders:async()=>true,
        createSubledgerOrderSettlement:async input=>{calls.push(['create',input]);return saves},
        changeSubledgerOrderSettlementStatus:async(...input)=>{calls.push(['status',...input]);return true},
        reverseSubledgerOrderSettlement:async(...input)=>{calls.push(['reverse',...input]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls,allowSave}=await server.ssrLoadModule('\0bridge-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/SubledgerOrderSettlements.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['finance'],permissions:['subledger_order_settlement.view','finance.record','finance.reverse']}
  const line={id:1,kind:'receivable',party_id:1,account_id:1,account_code:'AR',party_name:'客户甲',document_reference:'OLD-CREDIT',outstanding_amount:'-30.00',auxiliary:[{kind:'project',id:1,name:'项目甲'}]}
  const group={account_id:1,outstanding_amount:'20.00',auxiliary:line.auxiliary,evidence:[{type:'journal',journal_id:1,order_id:1,source_key:'shipment:1',journal_date:'2026-01-10',amount:'20.00'}]}
  const order={kind:'receivable',order_id:1,party_id:1,outstanding_amount:'40.00',groups:[group],blockers:[]}
  store.subledgerOrderOptions={active:true,lines:[line],orders:[order,{...order,order_id:2,party_id:2},{...order,order_id:3,blockers:['没有过账凭证']}]}
  let bindings,search=''
  const Real={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real,{search})}).use(pinia))
  const row={id:177,document_no:'SOL-20261008-000099',direction:'historical_credit',status:'draft',version:1,reverses_id:null,amount:'2.00',document_reference:'OLD-CREDIT',approval:{version:2,status:'submitted'}}
  store.subledgerOrderSettlements=[row]
  assert.doesNotMatch(await render(),/>执行核销<|>取消草稿</)
  search='177';assert.match(await render(),/SOL-20261008-000099/)
  search='not-found';assert.doesNotMatch(await render(),/SOL-20261008-000099/);search=''
  store.subledgerOrderSettlements=[{...row,approval:{version:3,status:'approved'}}]
  assert.match(await render(),/>执行核销</)
  bindings.start();bindings.form.value.opening_line_id=1;await nextTick()
  Object.assign(bindings.form.value,{order_id:1,amount:'2',reference:'R',reason:'核对来源'})
  assert.equal(bindings.orders.value.length,1);assert.equal(bindings.limit.value,2000n)
  await bindings.save();assert.equal(bindings.editing.value,true);assert.equal(bindings.form.value.reference,'R')
  allowSave();await bindings.save();assert.equal(bindings.editing.value,false)
  bindings.ask(store.subledgerOrderSettlements[0],'post');bindings.reason.value='核对执行'
  store.subledgerOrderSettlements=[{...row,approval:{version:4,status:'approved'}}]
  await bindings.confirm();assert.equal(calls.filter(call=>call[0]==='status').length,0);assert.match(store.error,/核销或审批已变化/)
  store.subledgerOrderSettlements=[{...row,approval:{version:3,status:'approved'}}]
  await bindings.confirm();assert.equal(calls.filter(call=>call[0]==='status').length,1)
  store.user.permissions=['subledger_order_settlement.view']
  assert.doesNotMatch(await render(),/>新增历史与订单核销<|>执行核销<|>取消草稿</)
})
