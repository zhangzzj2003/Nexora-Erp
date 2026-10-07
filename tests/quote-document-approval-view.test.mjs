import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 实际报价页面验证统一入口和已打开转单弹窗；只替换绘制，保留真实条件与 Pinia 状态。
test('报价列表使用本单审批，原批准不能放行转单，撤回与撤权阻止已打开弹窗',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'quote-approval-view-fixture',enforce:'pre',
    transform(code,id){if(id.endsWith('/CustomerRelationsView.vue'))return code.replace("'naive-ui'","'virtual:quote-modal'")},
    resolveId(id,importer){
      if(id==='virtual:quote-modal')return '\0quote-modal'
      if(importer?.includes('/CustomerRelationsView.vue') && id.endsWith('/store/app-store'))return '\0quote-store'
      if(id.endsWith('/AppButton.vue'))return '\0quote-button'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0quote-table'
      for(const name of ['CrmEvidence.vue','CrmEditor.vue','ContactImportDialog.vue','OpportunityImportDialog.vue','DocumentApprovalDialog.vue','WorkspaceSelect.vue']){
        if(id.endsWith('/'+name))return '\0quote-stub'
      }
    },load(id){
      if(id==='\0quote-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0quote-stub')return 'export default {render:()=>null}'
      if(id==='\0quote-button')return `import {defineComponent,h} from 'vue';export const buttons=[];export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();buttons.push({label,click:attrs.onClick,disabled:p.disabled});return h('button',attrs,children)}}})`
      if(id==='\0quote-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0quote-store')return `import {ref} from 'vue';import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];const allowed=ref(true);export const setPermission=v=>allowed.value=v;
        export const usePiniaAppStore=defineStore('quote-approval-view',()=>{const state=createAppState();return {...state,can:()=>allowed.value,localTime:v=>v,clearCrmDetail:()=>{},loadCrm:async()=>true,
          loadCrmDetail:async(kind,id)=>{state.crmDetail.value={kind,record:state.crmOverview.value.quotes.find(row=>row.id===id)};return true},
          openDocumentApproval:target=>calls.push(['approval',target]),convertCrmQuote:async(...args)=>{calls.push(['convert',...args]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls,setPermission}=await server.ssrLoadModule('\0quote-store')
  const {buttons}=await server.ssrLoadModule('\0quote-button')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/CustomerRelationsView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,permissions:['crm.view','crm_quote.convert','sales_order.create']}
  const item={id:1,version:3,reference:'Q-1',status:'approved',customer_id:2,customer_name:'客户',contact_name:'',
    expired:false,contact_active:true,opportunity_stage:'qualified',opportunity_version:1,opportunity_title:'设备商机',review_blocked:[1],
    party:{customer_name:'客户',contact_name:'',phone:'',email:''},total_amount:'2',valid_until:'2030-01-31',terms:'固定商务条款',lines:[]}
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.mode.value='quote';return bindings}}
  const render=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))}
  for(const approval of [undefined,{status:'draft'},{status:'submitted'},{status:'withdrawn'}]){
    store.crmOverview={contacts:[],opportunities:[],activities:[],quotes:[{...item,approval}]}
    await render()
    assert.ok(!buttons.some(b=>['提交报价','批准报价','驳回报价','转销售草稿'].includes(b.label)))
    calls.length=0;await buttons.find(b=>b.label==='单据审批').click()
    assert.deepEqual(calls,[['approval',{document_type:'CrmQuote',document_id:1,intent:'execute'}]])
  }
  store.crmOverview.quotes=[{...item,approval:{status:'approved'}}]
  await render();await buttons.find(b=>b.label==='转销售草稿').click()
  bindings.reason.value='客户确认';bindings.acceptance.value='确认邮件'
  store.crmOverview.quotes[0].approval.status='withdrawn';calls.length=0
  await bindings.execute();assert.equal(calls.length,0)
  store.crmOverview.quotes[0].approval.status='approved'
  store.user.permissions=['crm.view'];await bindings.execute();assert.equal(calls.length,0)
  store.user.permissions=['crm.view','crm_quote.convert','sales_order.create']
  // 撤权会主动关闭原弹窗，重新读取详情后才能执行。
  await bindings.openCommand('quote',1,'convert');bindings.reason.value='客户确认';bindings.acceptance.value='确认邮件'
  await bindings.execute();assert.equal(calls[0][0],'convert')
  setPermission(false)
})
