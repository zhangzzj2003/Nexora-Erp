import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {createPinia} from 'pinia'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {ref} from 'vue';import {defineStore} from 'pinia';
export const usePiniaAppStore=defineStore('adjustment-view',()=>{
const stockAdjustments=ref([]);return {
stockAdjustments,error:ref(''),notice:ref(''),user:ref({id:1}),busy:ref(false),connectionLost:ref(false),
materials:ref([]),warehouses:ref([]),adjustmentDecisionReasons:ref({}),adjustmentReversalReasons:ref({}),
adjustmentForm:ref({warehouse_id:1,reason:'',reference:'',lines:[]}),
can:()=>true,localTime:value=>value,createStockAdjustment(){},submitStockAdjustment(){},
approveStockAdjustment(){},rejectStockAdjustment(){},cancelStockAdjustment(){},
loadAvailableAdjustmentLots(){},postStockAdjustment(){},reverseStockAdjustment(){}}});`

test('库存调整显示新增批次、旧差额及逐批仓库确认入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'adjustment-lot-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/warehouse/InventoryAdjustmentsView')
          && id.endsWith('/store/app-store'))return '\0adjustment-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0lot-approval-stub'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0adjustment-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0adjustment-view-select'
    },load(id){
      if(id==='\0lot-approval-stub')return `export default {render:()=>null}`
      if(id==='\0adjustment-view-store')return storeModule
      if(id==='\0adjustment-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[...
        (props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0adjustment-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }} ,vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0adjustment-view-store')
  const pinia=createPinia()
  const store=usePiniaAppStore(pinia)
  const line={id:7,material_id:3,sku:'A',material_name:'成品',unit:'件',quantity:'1.000'}
  const adjustment={id:2,warehouse_id:1,warehouse_name:'主仓库',reason:'盘差',reference:'',
    status:'posted',created_at:'2026-10-03',created_by_name:'admin',
    reversal_id:null,reversal_reason:null,lines:[{...line,physical_lots:[
      {id:8,code:'AD2-L7-P1',quantity:'1.000',source_kind:'adjustment'}]}]}
  store.stockAdjustments=[adjustment,{...adjustment,id:3,lines:[{...line,physical_lots:[]}]},
    {...adjustment,id:4,status:'approved',approval:{status:'approved'},lines:[{...line,physical_lots:[]}]}]
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryAdjustmentsView.vue')
  const html=await renderToString(createSSRApp({render:()=>h(Component)}).use(pinia))
  assert.match(html,/AD2-L7-P1/)
  assert.match(html,/调整新增/)
  assert.match(html,/普通确认，未指定实物批次/)
  assert.match(html,/仓库确认/)
  assert.equal((html.match(/普通确认，未指定实物批次/g)??[]).length,1)
})
