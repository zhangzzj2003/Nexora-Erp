import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {createPinia} from 'pinia'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {ref} from 'vue';import {defineStore} from 'pinia';
export const usePiniaAppStore=defineStore('shipment-view',()=>({
shipments:ref([]),error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
materials:ref([]),warehouses:ref([]),salesOrders:ref([]),shipmentReversalReasons:ref({}),
shipmentForm:ref({sales_order_id:0,warehouse_id:1,reference:'',lines:[]}),
can:()=>true,localTime:value=>value,chooseShipmentOrder(){},createShipment(){},
loadAvailableShipmentLots(){},postShipment(){},cancelShipment(){},reverseShipment(){}}));`

test('销售出库显示固定批次、旧单差额和指定批次确认入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'shipment-lot-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/sales/SalesShipmentsView')
          && id.endsWith('/store/app-store'))return '\0shipment-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0sales-proof-approval-dialog'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0shipment-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0shipment-view-select'
    },load(id){
      if(id==='\0sales-proof-approval-dialog')return `export default {render:()=>null}`
      if(id==='\0shipment-view-store')return storeModule
      if(id==='\0shipment-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[...
        (props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0shipment-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }} ,vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0shipment-view-store')
  const line={id:7,material_id:3,sku:'A',material_name:'成品',unit:'件',quantity:'1.000',
    returned_quantity:'0',returnable_quantity:'1.000'}
  const shipment={id:2,sales_order_id:1,warehouse_id:1,warehouse_name:'主仓库',customer_name:'客户',
    reference:'',status:'posted',created_at:'2026-10-02',created_by_name:'admin',
    reversal_id:null,reversal_reason:null,lines:[{...line,physical_lots:[
      {id:8,code:'LEGACY-W1-M3',quantity:'1.000',source_kind:'legacy'}]}]}
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.shipments=[shipment,{...shipment,id:3,lines:[{...line,physical_lots:[]}]},
    {...shipment,id:4,status:'draft',approval:{status:'approved'},lines:[{...line,physical_lots:[]}]}]
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/SalesShipmentsView.vue')
  const html=await renderToString(createSSRApp({render:()=>h(Component)}).use(pinia))
  assert.match(html,/LEGACY-W1-M3/)
  assert.match(html,/历史未识别/)
  assert.match(html,/普通确认未指定实物批次/)
  assert.match(html,/指定实物批次（可选）/)
  assert.equal((html.match(/普通确认未指定实物批次/g)??[]).length,1)
})
