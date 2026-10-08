import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

test('实际核销页面匹配归属、保留失败输入，并拒绝过期审批执行',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'subledger-settlement-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/SubledgerSettlements.vue'))return code.replaceAll("'naive-ui'","'virtual:settlement-modal'")},
    resolveId(id,importer){
      if(id==='virtual:settlement-modal')return '\0settlement-modal'
      if(importer?.includes('/SubledgerSettlements.vue') && id.endsWith('/store/app-store'))return '\0settlement-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0settlement-table'
      if(id.endsWith('/AppButton.vue'))return '\0settlement-button'
      if(id.endsWith('/WorkspaceSelect.vue')||id.endsWith('/AppInput.vue'))return '\0settlement-stub'
    },load(id){
      if(id==='\0settlement-stub')return 'export default {render:()=>null}'
      if(id==='\0settlement-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0settlement-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0settlement-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0settlement-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];export let saves=false;export const allowSave=()=>{saves=true};
        export const usePiniaAppStore=defineStore('settlement-view',()=>{const state=createAppState();return {...state,
        can:code=>state.user.value?.permissions.includes(code),openDocumentApproval:async()=>{},querySubledger:async()=>true,
        createSubledgerSettlement:async input=>{calls.push(['create',input]);return saves},
        changeSubledgerSettlementStatus:async(...input)=>{calls.push(['status',...input]);return true},
        reverseSubledgerSettlement:async(...input)=>{calls.push(['reverse',...input]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls,allowSave}=await server.ssrLoadModule('\0settlement-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/SubledgerSettlements.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['finance'],permissions:['subledger_opening.view','finance.record','finance.reverse']}
  const source={id:1,opening_id:1,kind:'receivable',account_id:1,party_id:1,party_name:'客户甲',account_code:'AR',document_reference:'CREDIT',outstanding_amount:'-50.00',auxiliary:[{kind:'project',id:1,name:'项目甲'}]}
  store.subledgerReport={to_date:'2026-10-08',rows:[source,{...source,id:2,document_reference:'DEBT',outstanding_amount:'100.00'},{...source,id:3,party_id:2,outstanding_amount:'100.00'}]}
  let bindings
  const Real={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real,{search:''})}).use(pinia))
  const row={id:1,status:'draft',version:1,reverses_id:null,amount:'30.00',from_document_reference:'CREDIT',to_document_reference:'DEBT',approval:{version:2,status:'submitted'}}
  store.subledgerSettlements=[row]
  assert.doesNotMatch(await render(),/>执行核销<|>取消草稿</)
  store.subledgerSettlements=[{...row,approval:{version:3,status:'approved'}}]
  assert.match(await render(),/>执行核销</)
  bindings.start();bindings.form.value={from_line_id:1,to_line_id:2,amount:'30',reference:'R',reason:'原单核对'}
  assert.equal(bindings.targets.value.length,1)
  await bindings.save();assert.equal(bindings.editing.value,true);assert.equal(bindings.form.value.reference,'R')
  allowSave();await bindings.save();assert.equal(bindings.editing.value,false)
  bindings.ask(store.subledgerSettlements[0],'post');bindings.reason.value='核对执行'
  store.subledgerSettlements=[{...row,approval:{version:4,status:'approved'}}]
  await bindings.confirm();assert.equal(calls.filter(call=>call[0]==='status').length,0);assert.match(store.error,/核销或审批已变化/)
  store.subledgerSettlements=[{...row,approval:{version:3,status:'approved'}}]
  await bindings.confirm();assert.equal(calls.filter(call=>call[0]==='status').length,1)
  store.user.permissions=['subledger_opening.view'];assert.doesNotMatch(await render(),/>新增原单核销<|>执行核销<|>取消草稿</)
})
