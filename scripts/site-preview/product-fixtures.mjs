import { materials } from './fixtures.mjs'

// 产品验收使用隔离虚构数据；只读桥拒绝保存、启用及生产等真实写入。
export const productPreviewMaterials = [...materials, {...materials[4], id:6, sku:'EL-PC-000003', name:'智能控制板长续航版',
  specification:'DC 24 V · 四路控制 · 长续航配置', manufacturer_part_number:'DEMO-CTRL02'},
  {...materials[4],id:7,sku:'FG-A100-01',name:'A100 智能控制器',specification:'标准整机 · 主控板 + 铝合金外壳'},
  {...materials[4],id:8,sku:'PART-CASE-01',name:'铝合金外壳',unit:'套',specification:'120 × 80 × 35 mm'}]
export const productPreviewModels = [{id:1,code:'A100',name:'A100 控制系列',notes:'虚构机型，仅用于界面验收',version:1,
  created_by:3,created_at:'2026-10-15 08:00:00'}, {id:2,code:'PCBA',name:'通用主控板',notes:'可供多个成品系列引用的半成品',version:1,created_by:3,created_at:'2026-10-15 08:00:00'}]
export const productPreviewProfiles = [7,5,6].map((id,index)=>({id:index+1,material_id:id,kind:id===7?'finished':'semi_finished',model_id:id===7?1:2,
  can_sell:true,can_purchase:id!==7,can_produce:true,
  configuration_name:id===6?'长续航版':'标准版',model_code:id===7?'A100':'PCBA',model_name:id===7?'A100 控制系列':'通用主控板',version:1,
  created_by:3,created_at:'2026-10-15 08:00:00',material:productPreviewMaterials.find(row=>row.id===id)}))
export const productPreviewBoms = [
 {id:1,product_material_id:5,version:1,status:'retired',source_bom_id:null},
 {id:2,product_material_id:5,version:2,status:'active',source_bom_id:1},
 {id:3,product_material_id:6,version:1,status:'draft',source_bom_id:2},
 {id:4,product_material_id:7,version:1,status:'active',source_bom_id:null},
].map(bom=>{
 const product=productPreviewMaterials.find(row=>row.id===bom.product_material_id)
 const parent=bom.source_bom_id?{id:bom.source_bom_id,version:bom.source_bom_id===1?1:2,
   product_material_id:5,product_name:materials[4].name,product_sku:materials[4].sku}:null
 return {...bom,product_name:product.name,product_sku:product.sku,product_unit:product.unit,source_bom:parent,
  base_quantity:'1',note:'产品管理界面示例',created_by:3,created_by_name:'示例计划员',created_at:'2026-10-15 08:00:00',
  activated_by:null,activated_at:null,retired_by:null,retired_at:null,cancelled_by:null,cancelled_at:null,
  lines:bom.id===4?[{id:40,component_material_id:5,component_bom_id:2,component_bom_version:2,component_bom_status:'active',
    sku:materials[4].sku,material_name:materials[4].name,unit:materials[4].unit,quantity:'1'},
    {id:41,component_material_id:8,sku:'PART-CASE-01',material_name:'铝合金外壳',unit:'套',quantity:'1'}]:materials.slice(0,3).map((row,index)=>({id:bom.id*10+index,component_material_id:row.id,sku:row.sku,
    material_name:row.name,unit:row.unit,quantity:String([1,2,4][index])}))}
})
export const productPreviewOperations = ['queryProducts','productDetail','productChanges','productModels','productModelDetail',
 'productModelChanges','productBoms','bomDetail','boms','materials','materialUnits']
export function productPreviewResponse(action,payload){
 let result
 if(action==='queryProducts'){
   const rows=productPreviewProfiles.filter(row=>(!payload.kind||row.kind===payload.kind)&&(!payload.model_id||row.model_id===payload.model_id)
     && [row.material.sku,row.material.name,row.configuration_name,row.model_name,row.material.specification].join(' ').toLowerCase().includes(payload.query.trim().toLowerCase()))
   const page=Math.min(payload.page,Math.max(1,Math.ceil(rows.length/payload.page_size)))
   result={items:rows.slice((page-1)*payload.page_size,page*payload.page_size),total:rows.length,page,page_size:payload.page_size}
 }else if(action==='productModels')result=productPreviewModels
 else if(action==='productDetail')result=productPreviewProfiles.find(row=>row.id===payload.id)
 else if(action==='productChanges'||action==='productModelChanges')result=[]
 else if(action==='productModelDetail')result=productPreviewModels.find(row=>row.id===payload.id)
 else if(action==='productBoms')result=productPreviewBoms.filter(row=>row.product_material_id===payload.materialId)
 else if(action==='bomDetail')result=productPreviewBoms.find(row=>row.id===payload.bomId)
 else if(action==='boms')result=productPreviewBoms
 else if(action==='materials')result=productPreviewMaterials
 else if(action==='materialUnits')result=['个','件','块'].map((name,index)=>({id:index+1,name,enabled:true,notes:'',version:1,created_at:'2026-10-15 08:00:00',material_count:1}))
 if(result===undefined)throw Error('截图预览不支持此操作，未连接业务服务。')
 return structuredClone(result)
}
