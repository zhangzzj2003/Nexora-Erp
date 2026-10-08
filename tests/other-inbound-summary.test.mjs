import assert from 'node:assert/strict'
import { test } from 'node:test'
import { computed, effectScope, ref } from 'vue'
import { otherInboundGroup, otherInboundSummary } from '../src/renderer/src/views/workspace/warehouse/other-inbound-summary.ts'
import { useLocalPagination } from '../src/renderer/src/composables/use-local-pagination.ts'

// 审批结束不代表已经入库，终态必须优先归入取消和冲销而非待处理。
test('入库统计分组互斥，已批准仍未处理，取消和冲销不计入待处理', () => {
  const rows = [
    ...['draft', 'submitted', 'approved', 'rejected', 'withdrawn', 'executed'].map(status => ({status:'draft',reversal_id:null,approval:{status}})),
    {status:'posted',reversal_id:null,approval:{status:'submitted'}},
    {status:'cancelled',reversal_id:null,approval:{status:'approved'}},
    {status:'posted',reversal_id:18},
    {status:'cancelled',reversal_id:19}
  ]
  const before = structuredClone(rows)
  assert.deepEqual(rows.map(otherInboundGroup), ['pending','pending','pending','pending','pending','pending','processed','cancelled','reversed','cancelled'])
  const summary = otherInboundSummary(rows)
  assert.deepEqual(summary, {all:10,pending:6,processed:1,cancelled:2,reversed:1})
  assert.equal(summary.pending + summary.processed + summary.cancelled + summary.reversed, summary.all)
  assert.deepEqual(rows, before)
  assert.deepEqual(otherInboundSummary([]), {all:0,pending:0,processed:0,cancelled:0,reversed:0})
})

// 使用真实响应式分页，验证状态切换、关键词交集及快照更新完整联动。
test('切换统计回到首页，搜索与状态组合筛选，统计保持完整快照且自动更新', () => {
  const scope = effectScope()
  const source = ref(Array.from({length:65},(_,i)=>({id:i+1,name:`入库-${i+1}`,status:i<45?'draft':'posted',reversal_id:null})))
  const query = ref(''), selected = ref('all')
  const summary = computed(()=>otherInboundSummary(source.value))
  const filtered = computed(()=>source.value.filter(item=>item.name.includes(query.value) && (selected.value==='all'||otherInboundGroup(item)===selected.value)))
  const filterKey = computed(()=>JSON.stringify([query.value,selected.value]))
  const pagination = scope.run(()=>useLocalPagination(filtered,filterKey))
  try {
    pagination.changePage(3,20)
    selected.value='processed'
    assert.equal(pagination.page.value,1)
    assert.equal(pagination.total.value,20)
    assert.ok(pagination.rows.value.every(item=>item.status==='posted'))
    query.value='入库-65'
    assert.equal(pagination.total.value,1)
    assert.equal(summary.value.all,65)
    selected.value='pending'
    assert.equal(pagination.total.value,0)
    assert.deepEqual(pagination.rows.value,[])
    selected.value='all'
    assert.equal(query.value,'入库-65')
    assert.equal(pagination.rows.value[0].id,65)
    query.value=''
    selected.value='pending'
    pagination.changePage(3,20)
    source.value=source.value.map(item=>item.id>40?{...item,status:'posted'}:item)
    assert.equal(summary.value.pending,40)
    assert.equal(summary.value.processed,25)
    assert.equal(pagination.page.value,2)
    assert.equal(source.value.length,65)
    source.value=[]
    assert.equal(summary.value.all,0)
    assert.equal(pagination.page.value,1)
  } finally { scope.stop() }
})
