import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

test('采购入库列表明确区分待登记、已登记与旧单未分配批次',async t=>{
  // 使用同一个 Pinia 状态，旧单无批次仍可查看，执行按钮只在已批准后出现。
  const fixture=`import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';
    export const usePiniaAppStore=defineStore('receipt-lot-view',()=>({ ...createAppState(),
      can:code=>code==='receipt.post',localTime:value=>value,postReceipt(){},reverseReceipt(){},openDocumentApproval(){}}));`
  const server=await createServer({configFile:false,plugins:[{
    name:'receipt-lot-view-fixture',enforce:'pre',resolveId(id,importer){
      if(importer?.includes('/purchase/PurchaseReceiptsView') && id.endsWith('/store/app-store'))return '\0receipt-lot-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0receipt-approval-dialog'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0receipt-lot-table'
    },load(id){if(id==='\0receipt-lot-store')return fixture
      if(id==='\0receipt-approval-dialog')return `export default {render:()=>null}`
      if(id==='\0receipt-lot-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[slots.filters?.(),...(props.data??[]).flatMap(row=>['document','status','details','actions'].map(key=>slots['cell-'+key]?.({row}))),slots.empty?.()])}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0receipt-lot-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/purchase/PurchaseReceiptsView.vue')
  const render=()=>renderToString(createSSRApp({render:()=>h(View)}).use(pinia))
  const receipt={id:3,supplier_name:'供应商',warehouse_name:'主仓库',created_at:'2026-10-02',
    created_by_name:'admin',purchase_order_id:null,goods_receipt_id:null,reference:'',reversal_id:null,
    reversal_reason:null,status:'draft',lines:[{id:7,sku:'LOT-3',material_name:'物料',quantity:'2.125',
      unit:'件',returned_quantity:'0',physical_lots:[]}]}
  store.receipts=[receipt]
  assert.doesNotMatch(await render(),/>确认入库<|登记实物批次（可选）/)
  store.receipts=[{...receipt,approval:{status:'approved'}}]
  assert.match(await render(),/登记实物批次（可选）/)
  store.receipts=[{...receipt,status:'posted'}]
  assert.match(await render(),/普通入库，未登记实物批次/)
  store.receipts=[{...receipt,status:'posted',lines:[{...receipt.lines[0],physical_lots:[
    {id:1,code:'R3-L7-P1',quantity:'2.125',supplier_lot:null}]}]}]
  const posted=await render()
  assert.match(posted,/R3-L7-P1/)
  assert.match(posted,/供应商批号 未提供/)
  assert.doesNotMatch(posted,/未登记实物批次/)
})
