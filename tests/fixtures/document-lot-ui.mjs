// 统一的示例单据只用于 UI 回归和隔离预览，不读写真实服务或业务数据库。
export const lotViewCases = [
  ['warehouse/OtherInboundsView.vue','otherInbounds','inbound_line_id','其他入库 · 批次登记'],
  ['purchase/PurchaseReceiptsView.vue','receipts','receipt_line_id','采购入库 · 批次登记'],
  ['warehouse/WarehouseOutboundsView.vue','warehouseOutbounds','outbound_line_id','其他出库 · 批次选择'],
  ['warehouse/WarehouseTransfersView.vue','transfers','transfer_line_id','仓库调拨 · 批次选择'],
  ['warehouse/InventoryStocktakesView.vue','stocktakes','stocktake_line_id','库存盘点 · 差异批次'],
  ['warehouse/InventoryAdjustmentsView.vue','stockAdjustments','adjustment_line_id','库存调整 · 批次归属'],
  ['sales/SalesShipmentsView.vue','shipments','shipment_line_id','销售出库 · 批次选择'],
  ['sales/SalesReturnsView.vue','salesReturns','return_line_id','销售退货 · 回仓批次'],
  ['production/MaterialIssuesView.vue','materialIssues','material_issue_line_id','生产领料 · 批次选择'],
  ['production/MaterialReturnsView.vue','materialReturns','return_line_id','生产退料 · 回仓批次'],
  ['production/ProductionCompletionsView.vue','productionCompletions',null,'完工入库 · 成品批次']
]
export function documentLotFixture([file, state, lineKey]) {
  const line = {id:7,material_id:1,component_material_id:1,sku:'EL-CN-000001',material_name:'示例 · 2.54mm 排针 8P',unit:'条',quantity:'100',
    shipment_line_id:7,material_issue_line_id:7,book_quantity:'0',counted_quantity:'100',difference:'100',physical_lots:[],
    requested_quantity:'100',returned_quantity:'0',remaining_quantity:'100',accepted_quantity:'100',unit_price:'1',amount:'100'}
  const record = {id:1,document_no:'DEMO-20261007-000001',status:state==='stockAdjustments'?'approved':state==='productionCompletions'?'inspected':'draft',
    warehouse_id:1,warehouse_name:'示例原料仓',from_warehouse_id:1,to_warehouse_id:2,from_warehouse_name:'示例原料仓',to_warehouse_name:'示例成品仓',
    shipment_id:1,material_issue_id:1,work_order_id:1,purchase_order_id:1,goods_receipt_id:1,supplier_id:1,supplier_name:'示例供应商',customer_id:1,customer_name:'示例客户',
    reason:'gift',source_kind:'other',reference:'DEMO',note:'仅用于界面验证',created_by:1,created_by_name:'示例管理员',created_at:'2026-10-07T02:00:00Z',
    version:1,author_ids:[2],lines:[line],product_name:'示例 · 智能控制板',product_sku:'EL-PC-000005',product_unit:'块',
    accepted_quantity:'100',reported_quantity:'100',rejected_quantity:'0',remaining_output_quantity:'100',target_quantity:'100',bom_version:1,
    approval: ['shipments','salesReturns','materialIssues','materialReturns','productionCompletions'].includes(state) ? {status:'approved'} : undefined,
    posted_at:null,reversal_id:null,reversal_reason:null,attachments:[]}
  const options={warehouse_id:1,from_warehouse_id:1,to_warehouse_id:2,shipment_id:1,material_issue_id:1,
    lines:[{...line,[lineKey]:7,lots:[{lot_id:8,code:'SOURCE-01',source_kind:'receipt',quantity:'100',supplier_lot:'SUP-01',manufactured_on:null,expires_on:null}]}]}
  return {file,state,lineKey,record,options}
}
