import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 编译真实维护页面，原单批准撤回或业务版本变化后，已打开弹窗不能继续办理。
test('维护页面只显示统一审批，旧开始弹窗重核当前批准和业务版本',async t=>{
  const server=await createServer({configFile:false,plugins:[{
    name:'maintenance-approval-view',enforce:'pre',
    transform(code,id){if(id.endsWith('/EquipmentMaintenanceView.vue'))return code.replace("'naive-ui'","'virtual:maintenance-modal'")},
    resolveId(id,importer){
      if(id==='virtual:maintenance-modal')return '\0maintenance-modal'
      if(importer?.includes('/EquipmentMaintenanceView.vue') && id.endsWith('/store/app-store'))return '\0maintenance-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0maintenance-table'
      if(id.endsWith('/AppButton.vue'))return '\0maintenance-button'
      for(const file of ['EquipmentEditor.vue','EquipmentEvidence.vue','DocumentApprovalDialog.vue','WorkspaceSelect.vue','AppInput.vue'])if(id.endsWith('/'+file))return '\0maintenance-stub'
    },load(id){
      if(id==='\0maintenance-stub')return 'export default {render:()=>null}'
      if(id==='\0maintenance-modal')return `import {defineComponent,h} from 'vue';export const NCheckbox={render:()=>null};export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}})`
      if(id==='\0maintenance-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0maintenance-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0maintenance-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('maintenance-view-test',()=>{const state=createAppState();return {...state,
        can:code=>state.user.value?.permissions.includes(code),localTime:value=>value,loadEquipment:async()=>true,clearEquipmentDetail:()=>{},
        loadEquipmentDetail:async(kind,id)=>{state.equipmentDetail.value={kind,row:state.equipmentOverview.value.jobs.find(row=>row.id===id)};return true},
        changeMaintenanceJob:async input=>{calls.push(input);return true}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0maintenance-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/production/EquipmentMaintenanceView.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,roles:['admin'],permissions:['equipment.view','equipment.submit','equipment.review','equipment.execute']}
  const job={id:1,version:3,reference:'M-1',status:'approved',kind:'corrective',equipment_snapshot:{code:'EQ',name:'设备'},
    assigned_to_name:'执行人',parts:[],allowed_actions:['submit','approve','reject','start'],approval:{status:'approved'}}
  store.equipmentOverview={as_of:'2026-10-07',jobs:[job]}
  let bindings
  const RealView={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const html=await renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))
  assert.match(html,/单据审批/);assert.doesNotMatch(html,/提交审核|批准维护|驳回维护/)
  await bindings.prepare(1,'start')
  bindings.reason.value='按批准方案开始';bindings.evidence.value='现场检查依据'
  store.equipmentOverview.jobs=[{...job,approval:{status:'withdrawn'}}]
  await bindings.execute();assert.equal(calls.length,0);assert.match(store.error,/已变化/)
  store.equipmentOverview.jobs=[{...job,version:4}]
  await bindings.execute();assert.equal(calls.length,0)
  store.equipmentOverview.jobs=[job]
  await bindings.execute();assert.equal(calls.length,1);assert.equal(calls[0].id,1);assert.equal(calls[0].version,3)
  // 更正完成后仍可读取原独立批准；只有查看权限也保留历史入口。
  store.equipmentOverview.jobs=[{...job,status:'reversed',allowed_actions:[],reversal_approval:{version:2,status:'executed'}}]
  store.user.permissions=['equipment.view']
  const history=await renderToString(createSSRApp({render:()=>h(RealView)}).use(pinia))
  assert.match(history,/验收更正审批/)
})
