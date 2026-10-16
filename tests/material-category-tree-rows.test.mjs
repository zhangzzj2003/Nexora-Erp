import assert from 'node:assert/strict'
import { test } from 'node:test'
import { materialCategoryTreeRows } from '../src/renderer/src/views/workspace/catalog/material-category-tree.ts'

const entry=(code,name,enabled=true)=>({code,name,enabled,version:2,fields:[],notes:'',parent_code:code.includes('-')?code.split('-')[0]:null})
const catalog=[{...entry('EL','电子类'),children:[entry('EL-PC','电路板'),entry('EL-RE','电阻',false)]},
  {...entry('PL','塑料类',false),children:[entry('PL-HS','外壳'),entry('PL-OT','旧外壳',false)]}]

test('按完整大类保留层级和原顺序，手动折叠不修改目录资料',()=>{
  const before=JSON.stringify(catalog),collapsed=new Set(['EL'])
  const rows=materialCategoryTreeRows(catalog,'','all',collapsed)
  assert.deepEqual(rows.map(row=>[row.code,row.depth]),[['EL',0],['PL',0],['PL-HS',1],['PL-OT',1]])
  assert.equal(rows[0].expanded,false)
  assert.equal(rows[0].childCount,2)
  assert.equal(rows[2].path,'塑料类 / 外壳')
  assert.equal(JSON.stringify(catalog),before)
  assert.deepEqual([...collapsed],['EL'])
})

test('子类搜索与父级路径搜索保留祖先并临时展开，清空后恢复手动折叠',()=>{
  const collapsed=new Set(['EL'])
  const exact=materialCategoryTreeRows(catalog,' el-pc ','all',collapsed)
  assert.deepEqual(exact.map(row=>row.code),['EL','EL-PC'])
  assert.equal(exact[0].contextOnly,true)
  assert.equal(exact[0].expanded,true)
  assert.deepEqual(materialCategoryTreeRows(catalog,'电子类','all',collapsed).map(row=>row.code),['EL','EL-PC','EL-RE'])
  assert.deepEqual([...collapsed],['EL'])
  assert.ok(!materialCategoryTreeRows(catalog,'','all',collapsed).some(row=>row.code==='EL-PC'))
  assert.deepEqual(materialCategoryTreeRows(catalog,'不存在','all',collapsed),[])
})

test('状态按节点本身匹配，停用父类作为上下文保留且不伪造子类状态',()=>{
  const enabled=materialCategoryTreeRows(catalog,'','enabled',new Set(['PL']))
  assert.deepEqual(enabled.map(row=>row.code),['EL','EL-PC','PL','PL-HS'])
  assert.equal(enabled.find(row=>row.code==='PL').enabled,false)
  assert.equal(enabled.find(row=>row.code==='PL').contextOnly,true)
  assert.equal(enabled.find(row=>row.code==='PL-HS').enabled,true)
  assert.equal(enabled.find(row=>row.code==='PL-HS').parentEnabled,false)
  const disabled=materialCategoryTreeRows(catalog,'','disabled',new Set())
  assert.deepEqual(disabled.map(row=>row.code),['EL','EL-RE','PL','PL-OT'])
  assert.equal(disabled[0].contextOnly,true)
})

test('旧目录仍展示父子身份但无维护能力，删除节点不会重新出现在目录',()=>{
  const legacy=[{code:'OLD',name:'旧材料',children:[{code:'OLD-AA',name:'历史子类'}]}]
  const rows=materialCategoryTreeRows(legacy,'','all',new Set())
  assert.deepEqual(rows.map(row=>row.code),['OLD','OLD-AA'])
  assert.ok(rows.every(row=>row.manageable===false && row.enabled===undefined))
  assert.deepEqual(materialCategoryTreeRows(legacy,'','enabled',new Set()),[])
  const removed=[{...catalog[0],children:[{...catalog[0].children[0],deleted:true},catalog[0].children[1]]},{...catalog[1],deleted:true}]
  assert.deepEqual(materialCategoryTreeRows(removed,'','all',new Set()).map(row=>row.code),['EL','EL-RE'])
})
