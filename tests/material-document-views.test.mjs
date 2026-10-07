import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { documentRows } from '../src/renderer/src/utils/document-rows.ts'

const views = [
  ['purchase/PurchaseRequestsView.vue','purchaseRequestForm'],
  ['purchase/PurchaseOrdersView.vue','purchaseForm'],
  ['warehouse/WarehouseOutboundsView.vue','otherOutboundForm'],
  ['warehouse/WarehouseTransfersView.vue','transferForm'],
  ['warehouse/InventoryStocktakesView.vue','stocktakeForm'],
  ['warehouse/InventoryAdjustmentsView.vue','adjustmentForm'],
  ['sales/SalesOrdersView.vue','salesForm'],
  ['sales/SalesShipmentsView.vue','shipmentForm'],
  ['catalog/ProductionBomsView.vue','bomForm'],
  ['purchase/PurchaseGoodsReceiptsView.vue','goodsReceiptForm'],
  ['purchase/PurchaseReturnsView.vue','purchaseReturnForm'],
  ['sales/SalesReturnsView.vue','salesReturnForm'],
  ['production/MaterialIssuesView.vue','materialIssueForm'],
  ['production/MaterialReturnsView.vue','materialReturnForm']
]
const storeSource = `import { ref, reactive } from 'vue'
export const state = {}
export const editLoads=[]
for(const key of ${JSON.stringify(['materials','suppliers','warehouses','purchaseRequests','purchaseOrders','otherOutbounds','warehouseOutbounds','goodsReceipts','purchaseReturns','transfers','stocktakes','stockAdjustments','salesOrders','shipments','salesReturns','boms','workOrders','materialIssues','materialReturns','receipts'])})state[key]=ref([])
Object.assign(state,{busy:ref(false),connectionLost:ref(false),error:ref(''),notice:ref(''),version:ref('0.1.0'),user:ref({id:1,permissions:[]}),
 adjustmentDecisionReasons:ref({}),adjustmentReversalReasons:ref({}),otherOutboundReversalReasons:ref({}),transferReversalReasons:ref({}),stocktakeReversalReasons:ref({}),salesReturnReversalReasons:ref({}),requestRejectReasons:ref({}),
 can:()=>true,localTime:()=>'',openCustomers:()=>{},editPurchaseRequest:id=>{editLoads.push(id);state.purchaseRequestForm.value={...state.purchaseRequestForm.value,requestId:id??null,lines:[{material_id:0,quantity:'1'}]}}})
state.materialCategories=ref([])
state.materials.value=[{id:1,sku:'EL-SR-1',name:'电阻',unit:'个'},{id:2,sku:'HW-SC-2',name:'螺钉',unit:'件'}]
state.warehouses.value=[{id:1,name:'主仓库'}];state.suppliers.value=[{id:1,name:'供应商'}]
state.customers=ref([{id:1,name:'客户'}])
for(const key of ${JSON.stringify(views.map(v=>v[1]).concat('requestConversionForm'))})state[key]=ref({requestId:31,supplier_id:1,warehouse_id:1,from_warehouse_id:1,to_warehouse_id:2,customer_id:1,purchase_order_id:31,receipt_id:31,shipment_id:31,work_order_id:31,material_issue_id:31,product_material_id:2,base_quantity:'1',reference:'原参考号',note:'原说明',reason:'原原因',lines:[{material_id:1,component_material_id:1,quantity:'1',counted_quantity:'0',unit_price:'2.5000',warranty_days:30,warranty_basis:'合同',purchase_order_line_id:31,purchase_request_line_id:31,receipt_line_id:31,shipment_line_id:31,work_order_line_id:31,material_issue_line_id:31,accepted_quantity:'1',rejected_quantity:'0',rejection_reason:''}]})
const source={id:31,document_no:'PR-20261007-000031',status:'approved',lines:[{id:31,material_name:'来源物料',material_id:1,remaining_quantity:'3',returnable_quantity:'4'}]}
state.purchaseRequests.value=[source];state.purchaseOrders.value=[{...source,status:"confirmed"}]
for(const key of ['selectedPurchaseReturnReceipt','selectedSalesReturnShipment','selectedIssueOrder','selectedReturnIssue'])state[key]=ref(source)
export const useAppStore=()=>state
export const usePiniaAppStore=()=>reactive(state)
`
const modalSource = `import { defineComponent,h } from 'vue'
export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}})
export const NDatePicker=defineComponent({render:()=>null})
export const NPopconfirm=defineComponent({setup(p,{slots}){return()=>slots.default?.()}})
`
const tableSource = `import {defineComponent,h} from 'vue'
export default defineComponent({props:['title','data','columns'],setup(p,{slots}){return()=>h('section',{'data-table':p.title},[
 slots.actions?.(),slots.beforeTable?.(),p.title==='物料明细'?[slots.heading?.(),...p.data.map(row=>h('article',p.columns.map(c=>slots['cell-'+c.key]?.({row}))))]:null])}})
`
const buttonSource = `import {defineComponent,h} from 'vue'
export const buttons=[]
export default defineComponent({props:['type','disabled','loading'],setup(p,{slots,attrs}){return()=>{
 const children=slots.default?.();buttons.push({props:p,attrs,children});return h('button',{...attrs,type:p.type,disabled:p.disabled},children)
}}})`
const inputSource = `import {defineComponent,h} from 'vue'
export default defineComponent({props:['modelValue'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue})}})`
const selectSource = `import {defineComponent,h} from 'vue'
export default defineComponent({props:['modelValue','options'],setup(p,{attrs}){return()=>h('select',{...attrs,'data-selected':p.modelValue},p.options?.map(o=>h('option',{value:o.value,disabled:o.disabled},o.label)))}})`

// 使用真实页面与真实公共弹窗展开业务插槽，替换桌面桥接和表格渲染，避免测试连接正式服务。
test('十四个物料单据页面共用表格弹窗，新增和删除直接修改原草稿并保留业务字段', async t => {
  const server=await createServer({configFile:false,plugins:[{
    name:'material-document-fixtures',enforce:'pre',
    transform(code,id){
      if(id.includes('/views/workspace/') || id.endsWith('/WorkspaceDocumentDialog.vue')) {
        return code.replace(/const (showForm|createOpen|conversionOpen) = ref\(false\)/g,'const $1 = ref(true)')
          .replace("'naive-ui'","'virtual:material-document-modal'")
      }
    },
    resolveId(id,importer){
      if(id==='virtual:material-document-modal')return '\0material-document-modal'
      if(!importer?.includes('/src/renderer/'))return
      for(const [suffix,key] of [['/store/app-store','store'],['/WorkspaceTable.vue','table'],['/AppButton.vue','button'],['/AppInput.vue','input'],['/WorkspaceSelect.vue','select'],['/WorkspaceMaterialSelect.vue','select']]) {
        if(id.endsWith(suffix))return '\0material-document-'+key
      }
    },load(id){return {'\0material-document-store':storeSource,'\0material-document-modal':modalSource,'\0material-document-table':tableSource,
      '\0material-document-button':buttonSource,'\0material-document-input':inputSource,'\0material-document-select':selectSource}[id]}
  },vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom'})
  t.after(()=>server.close())
  const {state,editLoads}=await server.ssrLoadModule('\0material-document-store')
  const {buttons}=await server.ssrLoadModule('\0material-document-button')
  const render=async file=>{
    buttons.length=0
    const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/'+file)
    return renderToString(createSSRApp({render:()=>h(View)}))
  }
  for(const [file,form] of views) {
    const html=await render(file)
    assert.match(html,/data-table="物料明细"/,file)
    assert.match(html,/基础信息/,file)
    assert.match(html,/value="原参考号"|value="原原因"|value="原说明"/,file)
    const original=state[form].value.lines[0]
    // 可自由添加的页面均经公共按钮新增，复杂价格及保修字段仍属于原草稿。
    const text=nodes=>nodes.map(n=>typeof n.children==='string'?n.children:Array.isArray(n.children)?text(n.children):'').join('')
    const add=buttons.find(b=>text(b.children??[]).includes('添加物料'))
    if(add && !add.props.disabled) {
      add.attrs.onClick()
      assert.equal(state[form].value.lines.length,2,file)
      assert.equal(state[form].value.lines[0],original,file)
      const second=state[form].value.lines[1]
      assert.equal(second.material_id??second.component_material_id,0,file)
      assert.equal(second.quantity??second.counted_quantity,form==='stocktakeForm'?'0':'1',file)
      await render(file)
      const remove=buttons.filter(b=>text(b.children??[]).includes('移除')).at(0)
      remove.attrs.onClick()
      assert.equal(state[form].value.lines[0],second,file)
    }
  }
  // 新建入口再次打开现有未保存草稿时保留行；从已有申请切换到新单时才初始化。
  state.purchaseRequestForm.value.requestId=null
  const savedDraft=state.purchaseRequestForm.value.lines
  await render('purchase/PurchaseRequestsView.vue')
  const create=buttons.find(b=>(b.children??[]).some(n=>typeof n.children==='string'&&n.children.trim()==='新建采购申请'))
  create.attrs.onClick()
  assert.equal(editLoads.length,0)
  assert.equal(state.purchaseRequestForm.value.lines,savedDraft)
  state.purchaseRequestForm.value.requestId=31
  create.attrs.onClick()
  assert.equal(editLoads.length,1)
  assert.equal(state.purchaseRequestForm.value.requestId,null)
  // 转单标题使用正式业务单号，不能在布局迁移后退回内部 ID。
  assert.match(await render('purchase/PurchaseRequestsView.vue'), /申请 PR-20261007-000031 转采购订单/)
  const purchase=await render('purchase/PurchaseOrdersView.vue')
  assert.match(purchase,/step="0.0001"/)
  const adjustment=await render('warehouse/InventoryAdjustmentsView.vue')
  assert.match(adjustment,/min="-1000000"/)
  const stocktake=await render('warehouse/InventoryStocktakesView.vue')
  assert.match(stocktake,/min="0"/)
  const sales=await render('sales/SalesOrdersView.vue')
  assert.match(sales,/约定保修天数/)
  assert.match(sales,/合同或承诺依据/)
  for(const file of ['purchase/PurchaseGoodsReceiptsView.vue','purchase/PurchaseReturnsView.vue','sales/SalesReturnsView.vue','production/MaterialIssuesView.vue','production/MaterialReturnsView.vue']) {
    const html=await render(file)
    assert.doesNotMatch(html,/＋ 添加物料/,file)
    assert.match(html,/来源物料/,file)
  }
  assert.match(await render('production/MaterialIssuesView.vue'),/max="3"/)
  assert.match(await render('production/MaterialReturnsView.vue'),/max="4"/)
  // 公共事件也检查忙碌及行数上限，不能通过直接触发点击绕过禁用按钮。
  const beforeBusy=state.purchaseForm.value.lines.length
  state.busy.value=true
  await render('purchase/PurchaseOrdersView.vue')
  const blocked=buttons.find(b=>(b.children??[]).some(n=>typeof n.children==='string' && n.children.includes('添加物料')))
  assert.equal(blocked.props.disabled,true)
  blocked.attrs.onClick()
  assert.equal(state.purchaseForm.value.lines.length,beforeBusy)
  state.busy.value=false
  state.purchaseForm.value.lines=Array.from({length:100},()=>({material_id:1,quantity:'1',unit_price:'0'}))
  await render('purchase/PurchaseOrdersView.vue')
  const limit=buttons.find(b=>(b.children??[]).some(n=>typeof n.children==='string' && n.children.includes('添加物料')))
  assert.equal(limit.props.disabled,true)
  limit.attrs.onClick()
  assert.equal(state.purchaseForm.value.lines.length,100)
  state.connectionLost.value=true
  assert.match(await render('purchase/PurchaseOrdersView.vue'),/<fieldset disabled/)
  state.connectionLost.value=false
  state.can=()=>false
  assert.doesNotMatch(await render('purchase/PurchaseRequestsView.vue'),/data-modal=/)
})

test('删掉中间行后，表格行索引更新且编辑仍指向正确的业务对象',()=>{
  const lines=[{material_id:1,quantity:'1'},{material_id:2,quantity:'2'},{material_id:3,quantity:'3'}]
  const last=lines[2]
  documentRows(lines)[1].line.quantity='5'
  assert.equal(lines[1].quantity,'5')
  lines.splice(1,1)
  const rows=documentRows(lines)
  assert.equal(rows[1].line,last)
  assert.equal(rows[1].index,1)
  rows[1].line.quantity='9'
  assert.equal(last.quantity,'9')
})
