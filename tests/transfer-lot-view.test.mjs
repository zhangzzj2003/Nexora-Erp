import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {ref} from 'vue';import {defineStore} from 'pinia';
const transfers=ref([]);export const usePiniaAppStore=defineStore('transfer-lot-fixture',()=>({
transfers,error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
materials:ref([]),warehouses:ref([]),transferReversalReasons:ref({}),
transferForm:ref({from_warehouse_id:1,to_warehouse_id:2,reference:'',lines:[]}),
can:()=>true,localTime:value=>value,createTransfer(){},
loadAvailableTransferLots(){},postTransfer(){},reverseTransfer(){}}));
export {transfers};`

test('仓库调拨显示固定批次、旧单差额和指定批次确认入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'transfer-lot-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/warehouse/WarehouseTransfersView')
          && id.endsWith('/store/app-store'))return '\0transfer-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0lot-approval-stub'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0transfer-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0transfer-view-select'
    },load(id){
      if(id==='\0lot-approval-stub')return `export default {render:()=>null}`
      if(id==='\0transfer-view-store')return storeModule
      if(id==='\0transfer-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[...
        (props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0transfer-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }} ,vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {transfers,usePiniaAppStore}=await server.ssrLoadModule('\0transfer-view-store')
  const pinia=createPinia();usePiniaAppStore(pinia)
  const line={id:7,material_id:3,sku:'A',material_name:'成品',unit:'件',quantity:'1.000'}
  const transfer={id:2,from_warehouse_id:1,to_warehouse_id:2,
    from_warehouse_name:'主仓库',to_warehouse_name:'第二仓',
    reference:'',status:'posted',created_at:'2026-10-02',created_by_name:'admin',
    reversal_id:null,reversal_reason:null,lines:[{...line,physical_lots:[
      {id:8,code:'LEGACY-W1-M3',quantity:'1.000',source_kind:'legacy'}]}]}
  transfers.value=[transfer,{...transfer,id:3,lines:[{...line,physical_lots:[]}]},
    {...transfer,id:4,status:'draft',approval:{status:'approved'},lines:[{...line,physical_lots:[]}]}]
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/WarehouseTransfersView.vue')
  const html=await renderToString(createSSRApp({render:()=>h(Component)}).use(pinia))
  assert.match(html,/LEGACY-W1-M3/)
  assert.match(html,/历史未识别/)
  assert.match(html,/普通调拨，未指定实物批次/)
  assert.match(html,/确认调拨/)
  assert.equal((html.match(/普通调拨，未指定实物批次/g)??[]).length,1)
})

