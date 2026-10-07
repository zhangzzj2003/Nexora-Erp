import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 编译实际凭证页面，只替换绘制外壳；审批门槛与执行前的版本核对仍运行真实页面逻辑。
test('期初统一审批及独立撤销保留历史入口，失效弹窗不能确认启用',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'opening-approval-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/OpeningBalancesView.vue'))return code.replaceAll("'naive-ui'","'virtual:journal-modal'")},
    resolveId(id,importer){
      if(id==='virtual:journal-modal')return '\0journal-modal'
      if(importer?.includes('/OpeningBalancesView.vue') && id.endsWith('/store/app-store'))return '\0journal-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0journal-table'
      if(id.endsWith('/AppButton.vue'))return '\0journal-button'
      for(const file of ['OpeningHistory.vue',
        'ProfitTransferPanel.vue','ProfitTransferEvidence.vue','AuxiliarySelector.vue','AppCollapseItem.vue',
        'DocumentApprovalDialog.vue','WorkspaceSelect.vue','AppInput.vue'])if(id.endsWith('/'+file))return '\0journal-stub'
    },load(id){
      if(id==='\0journal-stub')return 'export default {render:()=>null}'
      if(id==='\0journal-modal')return `import {defineComponent,h} from 'vue';export const NDatePicker={render:()=>null};export const NCheckbox={render:()=>null};export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0journal-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0journal-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0journal-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('opening-view-test',()=>{const state=createAppState();return {...state,
        can:code=>state.user.value?.permissions.includes(code),openDocumentApproval:async()=>{},editJournal:async()=>{},saveJournal:async()=>false,
        loadOpeningBalanceChanges:async()=>[],editOpeningBalance:async()=>{},saveOpeningBalance:async()=>false,changeOpeningBalanceStatus:async(...input)=>{calls.push(input);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0journal-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/OpeningBalancesView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['opening_balance.view','opening_balance.submit','opening_balance.review','opening_balance.confirm','opening_balance.cancel','opening_balance.reverse']}
  const row={id:1,version:3,reference:'凭据1',effective_date:'2026-01-01',note:'',status:'approved',author_ids:[1],total_debit:'10.00',lines:[]}
  store.openingBalances=[row]
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))
  let html=await render();assert.match(html,/单据审批/);assert.doesNotMatch(html,/>确认期初<|>批准<|>提交</)
  store.openingBalances=[{...row,approval:{status:'approved'}}]
  html=await render();assert.match(html,/>确认期初</);assert.doesNotMatch(html,/>取消草稿</)
  bindings.ask(store.openingBalances[0],'confirm');bindings.reason.value='过账依据'
  store.openingBalances=[{...row,approval:{status:'withdrawn'}}]
  await bindings.confirm();assert.equal(calls.length,0);assert.match(store.error,/期初方案已变化/)
  store.openingBalances=[{...row,version:4,approval:{status:'approved'}}]
  await bindings.confirm();assert.equal(calls.length,0)
  store.openingBalances=[{...row,approval:{status:'approved'}}]
  await bindings.confirm();assert.equal(calls.length,1);assert.equal(calls[0][1],'confirm')
  store.openingBalances=[{...row,status:'confirmed',approval:{status:'executed'},reversal_approval:{status:'draft'}}]
  html=await render();assert.match(html,/撤销审批/);assert.doesNotMatch(html,/>撤销期初</)
  store.openingBalances=[{...row,status:'confirmed',approval:{status:'executed'},reversal_approval:{status:'approved'},reversal_reason:'固定更正依据'}]
  html=await render();assert.match(html,/>撤销期初</)
  bindings.ask(store.openingBalances[0],'reverse');assert.equal(bindings.reason.value,'固定更正依据')
  store.openingBalances=[{...store.openingBalances[0],reversal_approval:{status:'withdrawn'}}]
  await bindings.confirm();assert.equal(calls.length,1)
  store.openingBalances=[{...row,status:'confirmed',approval:{status:'executed'}}];store.user.permissions=['opening_balance.view']
  assert.match(await render(),/单据审批/)
  store.openingBalances=[{...row,status:'confirmed'}];html=await render();assert.match(html,/保留历史流程/);assert.doesNotMatch(html,/未送审/)
})
