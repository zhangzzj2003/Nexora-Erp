import assert from 'node:assert/strict'
import {test} from 'node:test'
import {computed,effectScope,ref} from 'vue'
import {filterWarningRows,filterLotRows,lotSummary,warningTone} from '../src/renderer/src/views/workspace/warehouse/warehouse-insights.ts'
import {useLocalPagination} from '../src/renderer/src/composables/use-local-pagination.ts'

// 预警统计依赖服务端全范围；本地搜索、状态与分页不能修改这份证据。
test('预警筛选取状态与关键词交集，缺货、停用语义及原快照保持独立',()=>{
  const rows=['out_of_stock','low','normal','disabled'].map((status,id)=>({id,status,
    warehouse_code:'MAIN',warehouse_name:'主仓',sku:`MAT-${id}`,material_name:'电阻'}))
  const original=structuredClone(rows)
  assert.deepEqual(filterWarningRows(rows,'','attention').map(row=>row.id),[0,1])
  assert.deepEqual(filterWarningRows(rows,'  mat-1 ','attention').map(row=>row.id),[1])
  assert.equal(filterWarningRows(rows,'主仓','all').length,4)
  assert.equal(filterWarningRows(rows,'电阻','disabled')[0].id,3)
  assert.equal(filterWarningRows(rows,'不存在','all').length,0)
  assert.deepEqual(rows.map(row=>warningTone(row.status)),['danger','pending','success','neutral'])
  assert.equal(warningTone('未知'),'neutral')
  assert.deepEqual(rows,original)
})

test('批次搜索支持供应商批号，历史未识别独立分组且跨仓不误算为唯一批次数',()=>{
  const rows=[{lot_id:1,warehouse_id:1,warehouse_name:'主仓',sku:'A-1',material_name:'螺丝',lot_code:'LOT-A',supplier_lot:'Supplier-X',source_kind:'receipt'},
    {lot_id:1,warehouse_id:2,warehouse_name:'副仓',sku:'A-1',material_name:'螺丝',lot_code:'LOT-A',supplier_lot:'Supplier-X',source_kind:'receipt'},
    {lot_id:2,warehouse_id:1,warehouse_name:'主仓',sku:'A-2',material_name:'垫片',lot_code:'LEGACY',supplier_lot:null,source_kind:'legacy'}]
  const original=structuredClone(rows)
  assert.deepEqual(lotSummary(rows),{all:3,identified:2,legacy:1})
  assert.equal(filterLotRows(rows,' supplier-x ','identified').length,2)
  assert.deepEqual(filterLotRows(rows,'垫片','legacy').map(row=>row.lot_id),[2])
  assert.equal(filterLotRows(rows,'lot-a','legacy').length,0)
  assert.equal(filterLotRows(rows,'副仓','all')[0].warehouse_id,2)
  assert.deepEqual(lotSummary([]),{all:0,identified:0,legacy:0})
  assert.deepEqual(rows,original)
})

test('预警和批次筛选均重置页码，分页后仍保留完整快照供统计与补证',()=>{
  const scope=effectScope()
  try{scope.run(()=>{
    const query=ref(''),kind=ref('all')
    const source=ref(Array.from({length:43},(_,id)=>({id,source_kind:id===42?'legacy':'receipt',
      warehouse_name:'主仓',sku:`MAT-${id}`,material_name:'零件',lot_code:`LOT-${id}`,supplier_lot:null})))
    const filtered=computed(()=>filterLotRows(source.value,query.value,kind.value))
    const key=computed(()=>JSON.stringify([query.value,kind.value]))
    const page=useLocalPagination(filtered,key)
    page.changePage(3,20)
    assert.equal(page.rows.value.length,3)
    kind.value='legacy'
    assert.equal(page.page.value,1)
    assert.equal(page.total.value,1)
    assert.equal(source.value.length,43)
    query.value='不存在'
    assert.equal(page.total.value,0)
    assert.equal(lotSummary(source.value).all,43)
  })}finally{scope.stop()}
})
