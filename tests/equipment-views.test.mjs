import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
const storeModule=`
import {defineStore} from 'pinia';import {ref} from 'vue';
export const usePiniaAppStore=defineStore('equipment-ui-test',()=>({
equipmentForms:ref({asset:{code:'',name:'',serial_number:'',location:'',status:'active',reason:''},plan:{equipment_id:1,reference:'',title:'',interval_days:30,next_due:'',enabled:true,reason:''},job:{equipment_id:1,reference:'',kind:'corrective',plan_id:null,work_order_id:null,assigned_to:1,request_note:'',warehouse_id:null,parts:[],reason:''}}),
equipmentEdit:ref(null),equipmentOverview:ref({as_of:'2026-10-01',equipment:[],plans:[],jobs:[],executors:[],materials:[],warehouses:[],work_orders:[]}),
server:ref(null),equipmentDetail:ref(null),equipmentLoading:ref(false),equipmentError:ref(''),busy:ref(false),error:ref(''),connectionLost:ref(false),user:ref({id:1,permissions:['equipment.view','equipment.manage','equipment.create']}),
can(code){return this.user.permissions.includes(code)},localTime:value=>value,loadEquipment(){},clearEquipmentDetail(){}
}));`
test('真实表单必填位置、工时未声明区别于零；只读和无权页面不展示写入口或生产来源',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'equipment-view-fixture',enforce:'pre',resolveId(id,importer){
    if(importer?.includes('/views/workspace/production/') && id.endsWith('/store/app-store'))return '\0equipment-view-store'
    if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0equipment-view-dialog'
    if(id.endsWith('/WorkspaceTable.vue'))return '\0equipment-view-table'
    // 门户控件依赖真实 document；此测试验证业务模板，控件交互由浏览器验收。
    if(id.endsWith('/WorkspaceSelect.vue'))return '\0equipment-view-select'
    if(id==='naive-ui' && importer?.includes('/views/workspace/production/Equipment'))return '\0equipment-view-naive'
  },load(id){if(id==='\0equipment-view-dialog')return 'export default {render:()=>null}';if(id==='\0equipment-view-store')return storeModule
    if(id==='\0equipment-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(_props,{slots}){return ()=>h('section',[slots.filters?.(),slots.actions?.(),slots.empty?.()])}})`
    if(id==='\0equipment-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    if(id==='\0equipment-view-naive')return `import {defineComponent,h} from 'vue';const Body=defineComponent({setup(_props,{slots}){return ()=>h('div',slots.default?.())}});export const NCheckbox=Body,NDatePicker=Body,NCollapse=Body;export const NModal=defineComponent({props:['show'],setup(props,{slots}){return ()=>props.show?h('div',slots.default?.()):null}})`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0equipment-view-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  async function render(file,props){const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/production/'+file+'.vue');return renderToString(createSSRApp({render:()=>h(Component,props)}).use(pinia))}
  const asset=await render('EquipmentEditor',{kind:'asset'})
  assert.match(asset,/设备位置/);assert.doesNotMatch(asset,/设备位置（选填）/)
  assert.match(asset,/设备位置[\s\S]*?<input[^>]*\brequired\b/)
  const detail={kind:'job',row:{id:1,version:1,reference:'M-1',status:'draft',kind:'corrective',equipment_snapshot:{code:'EQ-1',name:'设备'},assigned_to_name:'操作员',created_by_name:'编制人',request_note:'检查',work_order_linked:true,work_order_id:null,work_order_current_status:null,solution:'',labor_hours:null,service_amount:null,parts:[],plan_roll:{},changes:[]}}
  store.user.permissions=['equipment.view']
  const before=await render('EquipmentEvidence',{detail})
  assert.match(before,/未报工 \/ 未声明/);assert.match(before,/详细内容需生产查看权限/);assert.doesNotMatch(before,/生产工单 #/)
  detail.row.labor_hours='0.00';detail.row.service_amount='0.00'
  const explicit=await render('EquipmentEvidence',{detail});assert.match(explicit,/0.00 小时 \/ 0.00 元/)
  const readonly=await render('EquipmentMaintenanceView');assert.doesNotMatch(readonly,/新建维护工单/)
  store.user.permissions=[]
  const noaccess=await render('EquipmentMaintenanceView');assert.match(noaccess,/没有设备维护查看权限/);assert.doesNotMatch(noaccess,/搜索维护工单/)
})
