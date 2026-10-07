import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createSSRApp,h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'

// 编译真实资金页面，只替换外壳与服务；旧批准及撤回不能打开或继续执行。
test('资金页面保护独立批准执行、草稿取消与原记录反向入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'payment-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/PaymentRecordsView.vue'))return code.replaceAll("'naive-ui'","'virtual:payment-modal'")},
    resolveId(id,importer){
      if(id==='virtual:payment-modal')return '\0payment-modal'
      if(importer?.includes('/PaymentRecordsView.vue') && id.endsWith('/store/app-store'))return '\0payment-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0payment-table'
      if(id.endsWith('/AppButton.vue'))return '\0payment-button'
      for(const file of ['DocumentApprovalDialog.vue','AppInput.vue','WorkspaceSelect.vue'])if(id.endsWith('/'+file))return '\0payment-stub'
    },load(id){
      if(id==='\0payment-stub')return 'export default {render:()=>null}'
      if(id==='\0payment-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0payment-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0payment-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0payment-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('payment-view',()=>{const s=createAppState();return {...s,can:p=>s.user.value?.permissions.includes(p),localTime:v=>v,
        paymentActionLabel:row=>row.action,openDocumentApproval:async()=>{},createPaymentRecord:async()=>{},reversePaymentRecord:async()=>{},createOrderSettlement:async()=>{},reverseOrderSettlement:async()=>{},changePaymentRecordStatus:async(...input)=>{calls.push(input)},changeOrderSettlementStatus:async(...input)=>{calls.push(['offset',...input])}}})`
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0payment-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/PaymentRecordsView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['finance'],permissions:['finance.view','finance.record','finance.reverse']}
  const row={id:1,version:1,status:'draft',action:'settlement',amount:'10.00',reverses_id:null,reference:'BANK',party_name:'验收客户',created_at:'2026-10-07'}
  store.paymentRecords=[row]
  let bindings;const Real={...View,setup(p,c){bindings=View.setup(p,c);return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real)}).use(pinia))
  let html=await render();assert.match(html,/单据审批|取消草稿/);assert.doesNotMatch(html,/>确认资金<|建立反向草稿/)
  store.paymentRecords=[{...row,approval:{status:'approved'}}];html=await render()
  assert.match(html,/>确认资金</);assert.doesNotMatch(html,/>取消草稿</)
  bindings.ask(store.paymentRecords[0],'post');bindings.commandReason.value='核对执行'
  store.paymentRecords=[{...row,approval:{status:'withdrawn'}}]
  await bindings.confirmCommand();assert.equal(calls.length,0);assert.match(store.error,/批准已变化/)
  store.error='';store.paymentRecords=[{...row,approval:{status:'approved'}}];await render()
  bindings.ask(store.paymentRecords[0],'post');bindings.commandReason.value='核对执行'
  store.paymentRecords=[{...row,version:2,approval:{status:'approved'}}]
  await bindings.confirmCommand();assert.equal(calls.length,0)
  store.paymentRecords=[{...row,approval:{status:'approved'}}];await render()
  bindings.ask(store.paymentRecords[0],'post');bindings.commandReason.value='核对执行'
  await bindings.confirmCommand();assert.equal(calls.length,1);assert.equal(calls[0][1],'post')
  // 同业务版本撤回并重新批准后，旧弹窗必须因审批版本变化失效。
  store.paymentRecords=[{...row,approval:{status:'approved',version:4}}];await render()
  bindings.ask(store.paymentRecords[0],'post');bindings.commandReason.value='核对执行'
  store.paymentRecords=[{...row,approval:{status:'approved',version:8}}]
  await bindings.confirmCommand();assert.equal(calls.length,1)
  store.paymentRecords=[{...row,status:'executed'}];html=await render();assert.match(html,/历史执行记录/);assert.match(html,/建立反向草稿/)
  store.paymentRecords.push({...row,id:2,reverses_id:1,status:'draft'});html=await render();assert.doesNotMatch(html,/建立反向草稿/)
  store.paymentRecords[1].status='cancelled';assert.match(await render(),/建立反向草稿/)
  const transfer={id:8,version:1,status:'draft',reverses_id:null,amount:'6.00',reference:'OFFSET',party_name:'验收客户'}
  store.orderSettlements=[transfer];html=await render();assert.match(html,/核销审批/);assert.doesNotMatch(html,/>确认核销<|建立撤销草稿/)
  store.orderSettlements=[{...transfer,approval:{status:'approved',version:3}}];html=await render();assert.match(html,/>确认核销</)
  bindings.ask(store.orderSettlements[0],'post','OrderSettlementTransfer');bindings.commandReason.value='核对执行'
  store.orderSettlements=[{...transfer,approval:{status:'approved',version:7}}]
  await bindings.confirmCommand();assert.equal(calls.length,1)
  await render();store.error='';bindings.ask(store.orderSettlements[0],'post','OrderSettlementTransfer');bindings.commandReason.value='核对执行'
  await bindings.confirmCommand();assert.equal(calls.length,2);assert.equal(calls[1][0],'offset')
  store.orderSettlements=[{...transfer,status:'executed'}];assert.match(await render(),/建立撤销草稿/)
  store.orderSettlements.push({...transfer,id:9,reverses_id:8,status:'draft'});assert.doesNotMatch(await render(),/建立撤销草稿/)
  store.orderSettlements[1].status='cancelled';assert.match(await render(),/建立撤销草稿/)
})
