import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {setup as setupSsrStyles} from '@css-render/vue3-ssr'
import {renderToString} from '@vue/server-renderer'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

test('其他入库列表区分待登记、已登记和旧单未分配批次',async t=>{
  const fixture=`import {defineStore} from 'pinia';import {ref} from 'vue';
  export const usePiniaAppStore=defineStore('inbound-lot-ui-test',()=>({
    error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),materials:ref([]),warehouses:ref([]),
    otherInbounds:ref([]),otherInboundForm:ref({lines:[]}),otherInboundReversalReasons:ref({}),
    can:code=>code==='other_inbound.post',localTime:value=>value,
    createOtherInbound(){},postOtherInbound(){},cancelOtherInbound(){},reverseOtherInbound(){}
  }));`
  const server=await createServer({configFile:false,plugins:[{
    name:'other-inbound-lot-fixture',enforce:'pre',resolveId(id,importer){
      if(importer?.includes('/warehouse/OtherInboundsView')&&id.endsWith('/store/app-store'))return '\0other-inbound-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0inbound-approval-placeholder'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0other-inbound-table'
      if(id==='naive-ui'&&importer?.includes('OtherInboundsView'))return '\0other-inbound-naive'
    },load(id){if(id==='\0inbound-approval-placeholder')return 'export default {render(){return null}}';if(id==='\0other-inbound-store')return fixture
      if(id==='\0other-inbound-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[slots.filters?.(),...props.data.flatMap(row=>['document','source','lines','actions'].map(key=>slots['cell-'+key]?.({row}))),slots.empty?.()])}})`
      if(id==='\0other-inbound-naive')return `import {defineComponent,h} from 'vue';const Modal=defineComponent({props:{show:Boolean},setup(props,{slots}){return ()=>props.show?h('section',slots.default?.()):null}});export const NModal=Modal,NDatePicker=Modal;`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0other-inbound-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue')
  // 原生下拉菜单在服务端渲染时需要样式收集器，避免访问浏览器 document。
  const render=()=>{const app=createSSRApp({render:()=>h(View)}).use(pinia);setupSsrStyles(app);return renderToString(app)}
  const inbound={id:3,status:'draft',reason:'gift',note:'赠品',warehouse_name:'主仓库',created_at:'2026-10-02',
    created_by_name:'admin',reference:'GIFT',reversal_id:null,reversal_reason:null,
    lines:[{id:7,sku:'GIFT-3',material_name:'赠品物料',quantity:'2.125',unit:'件',physical_lots:[]}]}
  store.otherInbounds=[inbound]
  assert.doesNotMatch(await render(),/登记实物批次（可选）|>确认入库</)
  // 批准后普通入库与实物登记均可执行，未送审不能借批次弹窗绕过审批。
  store.otherInbounds=[{...inbound,approval:{status:'approved'}}]
  // 批次登记收纳到更多菜单，完整动作集合由操作菜单测试覆盖。
  assert.match(await render(),/更多单据操作/)
  assert.match(await render(),/>确认入库</)
  store.otherInbounds=[{...inbound,status:'posted'}]
  assert.match(await render(),/普通入库，未登记实物批次/)
  store.otherInbounds=[{...inbound,status:'posted',lines:[{...inbound.lines[0],physical_lots:[
    {id:1,code:'O3-L7-P1',quantity:'2.125',supplier_lot:null}]}]}]
  const posted=await render()
  assert.match(posted,/O3-L7-P1/)
  assert.match(posted,/来源批号 未提供/)
  assert.doesNotMatch(posted,/未登记实物批次/)
})
