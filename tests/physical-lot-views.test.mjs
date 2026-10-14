import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {setup as setupSsrStyles} from '@css-render/vue3-ssr'
import {createPinia} from 'pinia'
import {createRouter,createMemoryHistory} from 'vue-router'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {defineStore} from 'pinia';import {ref} from 'vue';
export const usePiniaAppStore=defineStore('physical-lot-ui-test',()=>(()=>{
const lotOverview=ref(null),lotHistory=ref(null),lotUnallocated=ref(null),lotLoading=ref(false),lotError=ref('');
const lotWarehouseId=ref(0),lotMaterialId=ref(0),warehouses=ref([{id:1,code:'MAIN',name:'主仓库'}]);
const materials=ref([{id:3,sku:'LOT-3',name:'试件'}]),busy=ref(false),connectionLost=ref(false),user=ref({id:1,permissions:['inventory.view']});
const ledgerQuery=ref({warehouse_id:null,material_id:null,from_date:'',to_date:'',source_type:null});
const server=ref({id:'test'}),allowed=ref(true);return {server,lotOverview,lotHistory,lotUnallocated,lotLoading,lotError,lotWarehouseId,lotMaterialId,
  warehouses,materials,busy,connectionLost,user,ledgerQuery,allowed,
  can(code){return allowed.value&&user.value.permissions.includes(code)},localTime:value=>value,
  loadPhysicalLots(){},loadPhysicalLotUnallocated(){},loadPhysicalLotHistory(){},savePhysicalLotEvidence(){},
  reversePhysicalLotEvidence(){},savePhysicalLotMovementEvidence(){},reversePhysicalLotMovementEvidence(){},
  savePhysicalLotEvidencePair(){},reversePhysicalLotEvidencePair(){},
  savePhysicalLotEvidenceGroup(){},reversePhysicalLotEvidenceGroup(){},clearPhysicalLotHistory(){}};
})());`

test('批次页面显示历史未识别、未分配差额、来源流水及无权状态',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'physical-lot-view-fixture',enforce:'pre',resolveId(id,importer){
    if(importer?.includes('/views/workspace/warehouse/PhysicalLotsView') && id.endsWith('/store/app-store'))return '\0lot-view-store'
    if(id.endsWith('/WorkspaceTable.vue'))return '\0lot-view-table'
    if(id.endsWith('/WorkspaceSelect.vue'))return '\0lot-view-select'
  },load(id){if(id==='\0lot-view-store')return storeModule
    if(id==='\0lot-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array,title:String,description:String,showTitle:Boolean},setup(props,{slots}){return ()=>h('section',[props.showTitle===false?null:h('h3',props.title),props.description,slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...(props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row}))),slots.empty?.()])}})`
    if(id==='\0lot-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0lot-view-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const router=createRouter({history:createMemoryHistory(),routes:[
    {path:'/',component:{render:()=>null}},
    {path:'/workspace/inventory-ledger',component:{render:()=>null}}]})
  await router.push('/');await router.isReady()
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/PhysicalLotsView.vue')
  // 渲染真实公共折叠项，注册样式上下文以覆盖默认收起与读屏结构。
  const render=()=>{
    const app=createSSRApp({render:()=>h(Component)}).use(pinia).use(router)
    setupSsrStyles(app)
    return renderToString(app)
  }
  const row={warehouse_id:1,warehouse_name:'主仓库',material_id:3,sku:'LOT-3',material_name:'试件',unit:'件',
    lot_id:7,lot_code:'LEGACY-W1-M3',source_kind:'legacy',supplier_lot:null,manufactured_on:null,expires_on:null,quantity:'2.000'}
  store.lotOverview={as_of:'2026-10-02 09:00:00',warehouse_id:null,material_id:null,rows:[row],
    differences:[{warehouse_id:1,warehouse_name:'主仓库',material_id:3,sku:'LOT-3',stock_quantity:'2.125',lot_quantity:'2.000',difference:'0.125'}],fully_allocated:false}
  const unallocated=await render()
  assert.match(unallocated,/历史未识别/)
  assert.match(unallocated,/未分配差额/)
  assert.match(unallocated,/0\.125/);assert.match(unallocated,/搜索批次/);assert.match(unallocated,/批次与补证说明/)
  // 长说明默认收起，由公共按钮保留键盘入口与展开状态；正文在用户展开后显示。
  assert.match(unallocated,/<button[^>]*app-collapse-trigger[^>]*aria-expanded="false"/)
  assert.doesNotMatch(unallocated,/现场补证<\/button>/)
  store.user={id:1,permissions:['inventory.view','physical_lot.reclassify']}
  assert.match(await render(),/现场补证/)
  store.user={id:1,permissions:['inventory.view','physical_lot.reclassify','physical_lot.movement_evidence']}
  store.lotUnallocated={checkpoint_movement_id:8,checkpoint_basis:'v56_opening',
    warehouse_id:null,material_id:null,has_more:false,rows:[{movement_id:9,warehouse_id:1,
      material_id:3,quantity:'0.125',unallocated_quantity:'0.125',source_type:'other_inbound',
      source_id:4,source_line_id:5,created_at:'2026-10-02 09:01:00'}]}
  assert.match(await render(),/待补证的旧客户端流水/)
  assert.match(await render(),/逐笔补证/)
  store.lotHistory={as_of:'2026-10-02 09:00:00',lot:{id:7,material_id:3,code:'LEGACY-W1-M3',source_kind:'legacy',
    supplier_lot:null,manufactured_on:null,expires_on:null,origin_movement_id:null,
    sku:'LOT-3',material_name:'试件',unit:'件'},
    openings:[{id:1,warehouse_id:1,warehouse_name:'主仓库',quantity:'2.000',checkpoint_movement_id:8,
      evidence:'无实物批次证据',created_at:'2026-10-02 09:00:00'}],
    movements:[{id:2,movement_id:9,warehouse_id:1,warehouse_name:'主仓库',quantity:'-0.125',
      source_type:'other_outbound',source_id:4,source_line_id:5,created_by_name:'admin',created_at:'2026-10-02 09:01:00',original_allocation_id:null}],
    reclassifications:[{id:3,warehouse_id:1,warehouse_name:'主仓库',quantity:'-0.500',
      counterpart_lot_id:8,counterpart_lot_code:'VERIFIED-1',evidence:'现场逐箱核对并签字确认',
      original_reclassification_id:null,created_by_name:'admin',created_at:'2026-10-02 09:02:00'}],
    movement_evidence:[{id:4,movement_id:9,warehouse_id:1,warehouse_name:'主仓库',quantity:'0.125',
      source_type:'other_inbound',source_id:4,source_line_id:5,evidence:'现场交接单与批次标签核对',
      original_evidence_id:null,created_by_name:'admin',created_at:'2026-10-02 09:03:00'}],
    evidence_pairs:[{id:5,inbound_movement_id:9,outbound_movement_id:10,
      inbound_evidence_id:6,outbound_evidence_id:7,quantity:'0.125',
      evidence:'入库箱码与出库交接记录逐件确认',original_pair_id:null,
      created_by_name:'admin',created_at:'2026-10-02 09:04:00'}],
    evidence_groups:[{id:8,evidence:'三笔流水按实物箱码整组核对',original_group_id:null,
      created_by_name:'admin',created_at:'2026-10-02 09:05:00',
      pairs:[{id:5,inbound_movement_id:9,outbound_movement_id:10,quantity:'0.125'},
        {id:6,inbound_movement_id:9,outbound_movement_id:11,quantity:'0.125'}]}],
    balances:[{warehouse_id:1,warehouse_name:'主仓库',quantity:'1.875'}]}
  const traced=await render()
  assert.match(traced,/升级检查点流水 #8/)
  assert.match(traced,/库存流水 #9/)
  assert.match(traced,/无实物批次证据/)
  assert.match(traced,/现场逐箱核对并签字确认/)
  assert.match(traced,/冲销补证/)
  assert.match(traced,/现场交接单与批次标签核对/)
  assert.match(traced,/冲销逐笔补证/)
  assert.match(traced,/入库箱码与出库交接记录逐件确认/)
  assert.match(traced,/整体冲销/)
  assert.match(traced,/三笔流水按实物箱码整组核对/)
  store.connectionLost=true
  assert.match(await render(),/旧批次余额与来源证据已失效/)
  store.allowed=false
  const denied=await render()
  assert.match(denied,/没有库存查看权限/)
  assert.doesNotMatch(denied,/未分配差额/)
})
