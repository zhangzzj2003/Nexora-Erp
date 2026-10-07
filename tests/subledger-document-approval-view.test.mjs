import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 编译实际凭证页面，只替换绘制外壳；审批门槛与执行前的版本核对仍运行真实页面逻辑。
test('分户方案统一审批与独立撤销保护启用入口及失效确认弹窗',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'opening-approval-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/SubledgerOpeningsView.vue'))return code.replaceAll("'naive-ui'","'virtual:journal-modal'")},
    resolveId(id,importer){
      if(id==='virtual:journal-modal')return '\0journal-modal'
      if(importer?.includes('/SubledgerOpeningsView.vue') && id.endsWith('/store/app-store'))return '\0journal-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0journal-table'
      if(id.endsWith('/AppButton.vue'))return '\0journal-button'
      for(const file of ['SubledgerEditor.vue','SubledgerEvidence.vue',
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
        loadSubledger:async()=>true,querySubledger:async()=>true,exportSubledger:async()=>{},editSubledger:async()=>true,loadSubledgerDetail:async()=>true,clearSubledgerDetail:()=>{},createSubledgerPayment:async()=>true,reverseSubledgerPayment:async()=>true,changeSubledgerStatus:async(...input)=>{calls.push(input);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0journal-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/SubledgerOpeningsView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['subledger_opening.view','subledger_opening.submit','subledger_opening.review','subledger_opening.confirm','subledger_opening.cancel','subledger_opening.reverse']}
  const row={id:1,version:3,reference:'凭据1',effective_date:'2026-01-01',note:'',status:'approved',author_ids:[1],total_debit:'10.00',lines:[]}
  store.subledgerOpenings=[row]
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.mode.value='plans';return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))
  let html=await render();assert.match(html,/单据审批/);assert.doesNotMatch(html,/>确认期初<|>批准<|>提交</)
  store.subledgerOpenings=[{...row,approval:{status:'approved'}}]
  html=await render();assert.match(html,/>确认期初</);assert.doesNotMatch(html,/>取消草稿</)
  bindings.ask(store.subledgerOpenings[0],'confirm');bindings.reason.value='过账依据'
  store.subledgerOpenings=[{...row,approval:{status:'withdrawn'}}]
  await bindings.confirm();assert.equal(calls.length,0);assert.match(store.error,/分户方案已变化/)
  store.subledgerOpenings=[{...row,version:4,approval:{status:'approved'}}]
  await bindings.confirm();assert.equal(calls.length,0)
  store.subledgerOpenings=[{...row,approval:{status:'approved'}}]
  await bindings.confirm();assert.equal(calls.length,1);assert.equal(calls[0][1],'confirm')
  store.subledgerOpenings=[{...row,status:'confirmed',approval:{status:'executed'},reversal_approval:{status:'draft'}}]
  html=await render();assert.match(html,/撤销审批/);assert.doesNotMatch(html,/>撤销期初</)
  store.subledgerOpenings=[{...row,status:'confirmed',approval:{status:'executed'},reversal_approval:{status:'approved'},reversal_reason:'固定更正依据'}]
  html=await render();assert.match(html,/>撤销期初</)
  bindings.ask(store.subledgerOpenings[0],'reverse');assert.equal(bindings.reason.value,'固定更正依据')
  store.subledgerOpenings=[{...store.subledgerOpenings[0],reversal_approval:{status:'withdrawn'}}]
  await bindings.confirm();assert.equal(calls.length,1)
  store.subledgerOpenings=[{...row,status:'confirmed',approval:{status:'executed'}}];store.user.permissions=['subledger_opening.view']
  assert.match(await render(),/单据审批/)
  store.subledgerOpenings=[{...row,status:'confirmed'}];html=await render();assert.match(html,/保留历史流程/);assert.doesNotMatch(html,/未送审/)
})
