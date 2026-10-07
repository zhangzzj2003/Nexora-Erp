import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用实际售后页面核对统一审批入口、下一步按钮及已打开弹窗的失效保护。
test('售后方案批准后才显示办理，结案更正独立审批且撤回阻止旧弹窗',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'after-approval-view-fixture',enforce:'pre',
    transform(code,id){if(id.endsWith('/AfterSalesView.vue'))return code.replace("'naive-ui'","'virtual:after-modal'")},
    resolveId(id,importer){
      if(id==='virtual:after-modal')return '\0after-modal'
      if(importer?.includes('/AfterSalesView.vue') && id.endsWith('/store/app-store'))return '\0after-store'
      if(id.endsWith('/AppButton.vue'))return '\0after-button'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0after-table'
      for(const name of ['AfterSalesEditor.vue','AfterSalesEvidence.vue','AfterSalesAttachments.vue','AfterSalesLaborCost.vue','AfterSalesRepairMargin.vue','DocumentApprovalDialog.vue','WorkspaceSelect.vue']){
        if(id.endsWith('/'+name))return '\0after-stub'
      }
    },load(id){
      if(id==='\0after-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0after-stub')return 'export default {render:()=>null}'
      if(id==='\0after-button')return `import {defineComponent,h} from 'vue';export const buttons=[];export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();buttons.push({label,click:attrs.onClick,disabled:p.disabled});return h('button',attrs,children)}}})`
      if(id==='\0after-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0after-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('after-approval-view',()=>{const state=createAppState();return {...state,can:code=>state.user.value?.permissions.includes(code),clearAfterSalesDetail:()=>{},loadAfterSales:async()=>true,
          loadAfterSalesDetail:async id=>{state.afterSalesDetail.value=state.afterSalesOverview.value.cases.find(row=>row.id===id);return true},
          openDocumentApproval:target=>calls.push(['approval',target]),changeAfterSalesCase:async(...args)=>{calls.push(['execute',...args]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0after-store')
  const {buttons}=await server.ssrLoadModule('\0after-button')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/AfterSalesView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['after_sales.view','after_sales.receive','after_sales.reverse','after_sales.cancel']}
  const item={id:1,version:3,reference:'A-1',status:'approved',kind:'repair',quantity:'2',charge_mode:'free',author_ids:[1],
    frozen_source:{customer_name:'客户',sku:'P',material_name:'商品',unit:'件'},current_source_valid:true}
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.mode.value='records';return bindings}}
  const render=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))}
  for(const approval of [undefined,{status:'draft'},{status:'submitted'},{status:'withdrawn'}]){
    store.afterSalesOverview={sources:[],cases:[{...item,approval}],materials:[],warehouses:[]}
    await render()
    assert.ok(!buttons.some(b=>['提交方案','批准方案','驳回申请','登记维修收件'].includes(b.label)))
    calls.length=0;await buttons.find(b=>b.label==='单据审批').click()
    assert.deepEqual(calls,[['approval',{document_type:'AfterSalesCase',document_id:1,intent:'execute'}]])
  }
  store.afterSalesOverview.cases=[{...item,approval:{status:'approved'}}]
  await render();await buttons.find(b=>b.label==='登记维修收件').click()
  bindings.reason.value='实际收件';bindings.evidence.value='交接记录'
  store.afterSalesOverview.cases[0].approval.status='withdrawn';calls.length=0
  await bindings.execute();assert.equal(calls.length,0)
  store.afterSalesOverview.cases=[{...item,status:'closed',approval:{status:'executed'},reversal_approval:{status:'draft'}}]
  await render();assert.ok(!buttons.some(b=>b.label==='更正已结案单'))
  calls.length=0;await buttons.find(b=>b.label==='结案更正审批').click()
  assert.deepEqual(calls,[['approval',{document_type:'AfterSalesCase',document_id:1,intent:'reverse'}]])
})
