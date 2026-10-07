import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {ref} from 'vue';import {defineStore} from 'pinia';
const stocktakes=ref([]);export const usePiniaAppStore=defineStore('stocktake-lot-fixture',()=>({
stocktakes,error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
materials:ref([]),warehouses:ref([]),stocktakeReversalReasons:ref({}),
stocktakeForm:ref({warehouse_id:1,reference:'',lines:[]}),
can:()=>true,localTime:value=>value,createStocktake(){},
loadAvailableStocktakeLots(){},postStocktake(){},cancelStocktake(){},reverseStocktake(){}}));
export {stocktakes};`

test('库存盘点显示实物批次、旧差额及核对入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'stocktake-lot-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/warehouse/InventoryStocktakesView')
          && id.endsWith('/store/app-store'))return '\0stocktake-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0lot-approval-stub'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0stocktake-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0stocktake-view-select'
    },load(id){
      if(id==='\0lot-approval-stub')return `export default {render:()=>null}`
      if(id==='\0stocktake-view-store')return storeModule
      if(id==='\0stocktake-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[...
        (props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0stocktake-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }} ,vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {stocktakes,usePiniaAppStore}=await server.ssrLoadModule('\0stocktake-view-store')
  const pinia=createPinia();usePiniaAppStore(pinia)
  const line={id:7,material_id:3,sku:'A',material_name:'成品',unit:'件',
    book_quantity:'1.000',counted_quantity:'2.000',difference:'1.000'}
  const stocktake={id:2,warehouse_id:1,warehouse_name:'主仓库',reference:'',
    status:'posted',created_at:'2026-10-03',created_by_name:'admin',
    reversal_id:null,reversal_reason:null,lines:[{...line,physical_lots:[
      {id:8,code:'ST2-L7-P1',quantity:'1.000',source_kind:'stocktake'}]}]}
  stocktakes.value=[stocktake,{...stocktake,id:3,lines:[{...line,physical_lots:[]}]},
    {...stocktake,id:4,status:'draft',approval:{status:'approved'},lines:[{...line,physical_lots:[]}]},
    {...stocktake,id:5,lines:[{...line,counted_quantity:'1.000',difference:'0.000',physical_lots:[]}]}]
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryStocktakesView.vue')
  const html=await renderToString(createSSRApp({render:()=>h(Component)}).use(pinia))
  assert.match(html,/ST2-L7-P1/)
  assert.match(html,/盘点发现/)
  assert.match(html,/普通确认，未指定实物批次/)
  assert.match(html,/确认盘点/)
  assert.equal((html.match(/普通确认，未指定实物批次/g)??[]).length,1)
})
