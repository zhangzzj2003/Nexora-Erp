import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 使用实际处置页面核对统一审批入口、下一步按钮及已打开弹窗的失效保护。
test('处置方案批准后才显示办理，结案更正独立审批且撤回阻止旧弹窗',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'quality-approval-view-fixture',enforce:'pre',
    transform(code,id){if(id.endsWith('/QualityDispositionView.vue'))return code.replace("'naive-ui'","'virtual:quality-modal'")},
    resolveId(id,importer){
      if(id==='virtual:quality-modal')return '\0quality-modal'
      if(importer?.includes('/QualityDispositionView.vue') && id.endsWith('/store/app-store'))return '\0quality-store'
      if(id.endsWith('/AppButton.vue'))return '\0quality-button'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0quality-table'
      for(const name of ['QualityEditor.vue','QualityEvidence.vue','DocumentApprovalDialog.vue']){
        if(id.endsWith('/'+name))return '\0quality-stub'
      }
    },load(id){
      if(id==='\0quality-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0quality-stub')return 'export default {render:()=>null}'
      if(id==='\0quality-button')return `import {defineComponent,h} from 'vue';export const buttons=[];export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();buttons.push({label,click:attrs.onClick,disabled:p.disabled});return h('button',attrs,children)}}})`
      if(id==='\0quality-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0quality-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('quality-approval-view',()=>{const state=createAppState();return {...state,can:code=>state.user.value?.permissions.includes(code),clearQualityDetail:()=>{},loadQuality:async()=>true,
          loadQualityDetail:async id=>{state.qualityDetail.value=state.qualityOverview.value.dispositions.find(row=>row.id===id);return true},
          openDocumentApproval:target=>calls.push(['approval',target]),changeQualityDisposition:async(...args)=>{calls.push(['execute',...args]);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0quality-store')
  const {buttons}=await server.ssrLoadModule('\0quality-button')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/production/QualityDispositionView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['quality.view','quality.post','quality.reverse','quality.cancel']}
  const item={id:1,version:3,reference:'Q-1',status:'approved',kind:'rework',quantity:'2',loss_treatment:'carry',author_ids:[1],
    frozen_source:{product_name:'成品',product_unit:'件'},current_source_valid:true,cost_allocation:null,created_by_name:'编制人'}
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.mode.value='records';return bindings}}
  const render=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))}
  for(const approval of [undefined,{status:'draft'},{status:'submitted'},{status:'withdrawn'}]){
    store.qualityOverview={cases:[],dispositions:[{...item,approval}],materials:[],warehouses:[]}
    await render()
    assert.ok(!buttons.some(b=>['提交处置','批准处置','驳回处置','确认处置'].includes(b.label)))
    calls.length=0;await buttons.find(b=>b.label==='单据审批').click()
    assert.deepEqual(calls,[['approval',{document_type:'QualityDisposition',document_id:1,intent:'execute'}]])
  }
  store.qualityOverview.dispositions=[{...item,approval:{status:'approved'}}]
  await render();await buttons.find(b=>b.label==='确认处置').click()
  bindings.reason.value='按已批准方案执行'
  store.qualityOverview.dispositions[0].approval.status='withdrawn';calls.length=0
  await bindings.execute();assert.equal(calls.length,0)
  store.qualityOverview.dispositions=[{...item,status:'posted',approval:{status:'executed'},reversal_approval:{status:'draft'}}]
  await render();assert.ok(!buttons.some(b=>b.label==='更正处置'))
  calls.length=0;await buttons.find(b=>b.label==='处置更正审批').click()
  assert.deepEqual(calls,[['approval',{document_type:'QualityDisposition',document_id:1,intent:'reverse'}]])
})
