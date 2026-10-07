import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 编译实际计划页面，核对统一入口和已打开转单弹窗的跨计划、撤回保护。
test('计划统一审批且旧转单弹窗不能套用其他计划或撤回的批准',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'mrp-approval-fixture',enforce:'pre',
    transform(code,id){if(id.endsWith('/MaterialPlanningView.vue'))return code.replace("'naive-ui'","'virtual:mrp-modal'")},
    resolveId(id,importer){
      if(id==='virtual:mrp-modal')return '\0mrp-modal'
      if(importer?.includes('/MaterialPlanningView.vue') && id.endsWith('/store/app-store'))return '\0mrp-store'
      if(id.endsWith('/AppButton.vue'))return '\0mrp-button'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0mrp-table'
      for(const name of ['MrpEditor.vue','MrpPolicies.vue','MrpEvidence.vue','DocumentApprovalDialog.vue','WorkspaceSelect.vue','AppInput.vue']){
        if(id.endsWith('/'+name))return '\0mrp-stub'
      }
    },load(id){
      if(id==='\0mrp-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0mrp-stub')return 'export default {render:()=>null}'
      if(id==='\0mrp-button')return `import {defineComponent,h} from 'vue';export const buttons=[];export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();buttons.push({label,click:attrs.onClick,disabled:p.disabled});return h('button',attrs,children)}}})`
      if(id==='\0mrp-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0mrp-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('mrp-approval-view',()=>{const state=createAppState();return {...state,localTime:value=>value,can:code=>state.user.value?.permissions.includes(code),clearMrpDetail:()=>{},loadMrp:async()=>true,
          loadMrpDetail:async item=>{state.mrpDetail.value=state.mrpPlans.value.find(row=>row.id===item.id);return true},
          openDocumentApproval:target=>calls.push(['approval',target]),convertMrpSuggestion:async(...args)=>{calls.push(['convert',...args]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0mrp-store')
  const {buttons}=await server.ssrLoadModule('\0mrp-button')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/production/MaterialPlanningView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['mrp.view','mrp.submit','mrp.review','mrp.convert','purchase_request.create']}
  const suggestion={key:'fixed',sku:'R',name:'电阻',quantity:'100',unit:'个',supply_mode:'buy',due_date:'2030-01-10'}
  const item={id:1,version:3,reference:'MRP-1',status:'approved',created_by_name:'编制人',start_date:'2030-01-01',conversions:[],author_ids:[1],snapshot:{suggestions:[suggestion]}}
  store.mrpPlans=[item];store.mrpCheck={matched:true}
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const render=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))}
  await render()
  assert.ok(!buttons.some(b=>['提交审核','批准计划','驳回计划'].includes(b.label)))
  await buttons.find(b=>b.label==='单据审批').click()
  assert.deepEqual(calls,[['approval',{document_type:'MrpPlan',document_id:1,intent:'execute'}]])
  store.mrpDetail={...item,approval:{status:'approved'}}
  bindings.openConversion(suggestion);assert.ok(bindings.conversion.value)
  bindings.reason.value='按批准建议采购';calls.length=0
  store.mrpDetail={...item,id:2,approval:{status:'approved'}}
  await bindings.convert();assert.equal(calls.length,0);assert.match(store.error,/计划或审批已变化/)
  store.mrpDetail={...item,approval:{status:'withdrawn'}}
  await bindings.convert();assert.equal(calls.length,0)
  store.mrpDetail={...item,approval:{status:'executed'}}
  await bindings.convert();assert.equal(calls[0][0],'convert');assert.equal(calls[0][1].id,1)
})
