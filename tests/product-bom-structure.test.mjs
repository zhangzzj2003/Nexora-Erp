import assert from 'node:assert/strict'
import { test } from 'node:test'
import { bomStructureRows } from '../src/renderer/src/views/workspace/catalog/bom-structure.ts'
import { productBody, productBomBody, validateProductResult } from '../src/shared/product-api.ts'

// 两个整机引用同一板卡时，结构保持独立分支，库存身份仍只有一份。
const line = (id, material, quantity='1', extra={}) => ({id,component_material_id:material,quantity,
  sku:`M${material}`,material_name:`物料${material}`,unit:'件',...extra})
const bom = (id, material, lines, extra={}) => ({id,product_material_id:material,version:id,
  base_quantity:'1',status:'active',product_name:`物料${material}`,product_sku:`M${material}`,
  product_unit:'件',lines,...extra})

test('多层组成按基准数量换算，展开不替换第一层领用物料', () => {
  const board = bom(2,20,[line(21,30,'3')],{base_quantity:'2'})
  const root = bom(1,10,[line(11,20,'2',{component_bom_id:2}),line(12,40,'4')])
  const collapsed = bomStructureRows(root,[root,board],new Set())
  assert.equal(collapsed.length,2)
  assert.equal(collapsed[0].childBom.id,2)
  assert.equal(collapsed[0].fixed,true)
  const expanded = bomStructureRows(root,[root,board],new Set(['1/11']))
  assert.deepEqual(expanded.map(row=>[row.sku,row.quantity,row.depth]),[
    ['M20','2.000',0],['M30','3.000',1],['M40','4.000',0]])
  assert.equal(root.lines.length,2)
  assert.equal(root.lines[0].component_material_id,20)
})

test('固定历史版本不随新默认切换，缺失或错误物料的版本不回退', () => {
  const old = bom(2,20,[line(21,30)],{status:'retired'})
  const current = bom(3,20,[line(31,40)])
  const root = bom(1,10,[line(11,20,'1',{component_bom_id:2})])
  const rows=bomStructureRows(root,[root,old,current],new Set(['1/11']))
  assert.equal(rows[0].childBom.id,2)
  assert.match(rows[0].issue,/停用/)
  assert.equal(rows[1].sku,'M30')
  const missing=bomStructureRows(root,[root,current],new Set(['1/11']))
  assert.equal(missing.length,1)
  assert.equal(missing[0].childBom,null)
  assert.match(missing[0].issue,/未加载/)
  assert.equal(bomStructureRows(root,[root,{...old,product_material_id:99}],new Set())[0].childBom,null)
  const unpinned=bomStructureRows({...root,lines:[line(11,20)]},[current],new Set())
  assert.equal(unpinned[0].fixed,false)
  assert.equal(unpinned[0].childBom.id,3)
})

test('多层循环停止展开，分数量换算使用整数且不修改原配方', () => {
  const root=bom(1,10,[line(11,20,'0.001',{component_bom_id:2})])
  const child=bom(2,20,[line(21,10,'0.001')],{base_quantity:'3'})
  const before=JSON.stringify([root,child])
  const rows=bomStructureRows(root,[root,child],new Set(['1/11','1/11/21']))
  assert.equal(rows.length,2)
  assert.match(rows[1].issue,/循环/)
  assert.equal(rows[1].quantity,'0.001')
  assert.equal(JSON.stringify([root,child]),before)
})

test('产品用途和组件配方经受限接口传递，错误类型不能绕过前端边界', () => {
  const base={kind:'semi_finished',model_id:null,configuration_name:'',material_id:20}
  const body=productBody({...base,can_sell:true,can_purchase:false,can_produce:true},false)
  assert.equal(body.can_sell,true);assert.equal(body.can_purchase,false)
  assert.throws(()=>productBody({...base,can_sell:'false'},false))
  const input={product_material_id:10,base_quantity:'1',note:'',lines:[
    {component_material_id:20,quantity:'1',component_bom_id:2,untrusted:'drop'}]}
  assert.deepEqual(productBomBody(input).lines,[{component_material_id:20,quantity:'1',component_bom_id:2}])
  assert.throws(()=>productBomBody({...input,lines:[{...input.lines[0],component_bom_id:'2'}]}))
  assert.throws(()=>validateProductResult('bomDetail',bom(1,10,[line(11,20,'1',{
    component_bom_id:2,component_bom_version:0,component_bom_status:'active'})])))
})
