import assert from 'node:assert/strict'
import {test} from 'node:test'
import {otherInboundLotIssue,inboundExcess} from '../src/renderer/src/views/workspace/warehouse/other-inbound-receiving.ts'
import {otherInboundActions} from '../src/renderer/src/views/workspace/warehouse/other-inbound-actions.ts'
import {otherInboundGroup} from '../src/renderer/src/views/workspace/warehouse/other-inbound-summary.ts'
import {inboundLotBody,validatePostedInboundLots} from '../src/shared/receipt-lot-validation.ts'
import {documentApprovalProgress} from '../src/renderer/src/utils/document-approval-progress.ts'

// 两条物料分次到货，只有实到批次才参与本次确认载荷。
const line={id:7,material_id:1,sku:'PART-A',quantity:'1000',received_quantity:'0',remaining_quantity:'1000',unit:'件'}
const inbound={id:3,status:'draft',approval:{status:'approved'},reversal_id:null,lines:[line]}
const part=quantity=>({quantity,supplier_lot:null,manufactured_on:null,expires_on:null})
const draft=(quantity,checkpoint='0')=>({inbound_line_id:7,expected_received_quantity:checkpoint,lots:[part(quantity)]})

test('本次实到800可确认，未到物料可跳过，零实收、溢收和过期检查点不可提交',()=>{
  assert.equal(otherInboundLotIssue(inbound,[draft('800')]),'')
  const multiple={...inbound,lines:[line,{...line,id:8}]}
  assert.equal(otherInboundLotIssue(multiple,[draft('800'),{inbound_line_id:8,expected_received_quantity:'0',lots:[]}]),'')
  assert.match(otherInboundLotIssue(inbound,[{...draft('800'),lots:[]}]),/至少登记/)
  assert.match(otherInboundLotIssue(inbound,[draft('1002')]),/溢收 2 件/)
  assert.deepEqual(inboundExcess(inbound,[draft('1002')]),[{line,quantity:'2'}])
  const partial={...inbound,status:'partially_posted',lines:[{...line,received_quantity:'800',remaining_quantity:'200'}]}
  assert.equal(otherInboundLotIssue(partial,[draft('200','800')]),'')
  assert.equal(otherInboundLotIssue({...partial,lines:[{...partial.lines[0],received_quantity:'800.000'}]},[draft('200','800')]),'')
  assert.match(otherInboundLotIssue(partial,[draft('200')]),/已经变化|已变化/)
  assert.match(otherInboundLotIssue(partial,[draft('200.001','800')]),/溢收 0.001/)
  for(const quantity of ['0','-1','1.0001','1e2',''])assert.match(otherInboundLotIssue(inbound,[draft(quantity)]),/批次数量/)
  assert.match(otherInboundLotIssue(inbound,[{...draft('800'),lots:[{...part('800'),manufactured_on:'2026-02-30'}]}]),/生产日期/)
  assert.match(otherInboundLotIssue(inbound,[{...draft('800'),lots:[{...part('800'),manufactured_on:'2026-10-09',expires_on:'2026-10-08'}]}]),/失效日期/)
  assert.match(otherInboundLotIssue(inbound,[draft('1'),draft('1')]),/明细已经变化/)
})

test('部分入库保留续收与独立冲销，已冲销关闭余量，不提供草稿取消',()=>{
  const partial={...inbound,status:'partially_posted'}
  const permissions={create:true,post:true,cancel:true,reverse:true}
  const actions=otherInboundActions(partial,permissions)
  assert.equal(actions.find(item=>item.key==='lots').label,'继续分批入库')
  assert.ok(actions.some(item=>item.key==='reversalApproval'))
  assert.ok(!actions.some(item=>item.key==='cancel'))
  assert.equal(otherInboundGroup(partial),'pending')
  const reversed={...partial,reversal_id:4}
  assert.equal(otherInboundGroup(reversed),'reversed')
  assert.deepEqual(otherInboundActions(reversed,permissions).map(item=>item.key),['approval'])
  assert.ok(!otherInboundActions(partial,{...permissions,post:false}).some(item=>item.key==='lots'))
})

test('IPC 携带累计实收检查点并核对本次追加证据，不能复用旧服务器或旧批次',()=>{
  const requested=[draft('200','800')]
  assert.equal(inboundLotBody({lines:requested}).lines[0].expected_received_quantity,'800')
  for(const expected of ['-1','NaN','0.0001',3,null])assert.throws(()=>inboundLotBody({lines:[{...draft('1'),expected_received_quantity:expected}]}),/检查点/)
  const response={id:3,status:'partially_posted',lines:[{id:7,quantity:'1000',received_quantity:'1000',remaining_quantity:'0',physical_lots:[
    {id:10,code:'ORIGINAL',...part('800')},{id:11,code:'SECOND',...part('200')}]},
    {id:8,quantity:'1000',received_quantity:'0',remaining_quantity:'1000',physical_lots:[]}]}
  assert.doesNotThrow(()=>validatePostedInboundLots(response,3,requested))
  assert.throws(()=>validatePostedInboundLots({...response,lines:[{...response.lines[0],received_quantity:'800'}]},3,requested))
  assert.throws(()=>validatePostedInboundLots({...response,lines:[{...response.lines[0],physical_lots:response.lines[0].physical_lots.slice(0,1)}]},3,requested))
  assert.throws(()=>validatePostedInboundLots({...response,status:'draft'},3,requested))
  assert.throws(()=>validatePostedInboundLots({...response,status:'posted'},3,requested))
  assert.throws(()=>validatePostedInboundLots({...response,lines:[{id:7,physical_lots:response.lines[0].physical_lots}]},3,requested))
})

test('部分执行历史不会把剩余入库显示为全部执行完毕',()=>{
  const progress=documentApprovalProgress({document_type:'WarehouseInbound',business_status:'partially_posted',intent:'execute',
    status:'approved',generation:1,version:3,current_step:1,steps:[{name:'批准',role:null}],events:[]})
  assert.equal(progress.nodes.at(-1).state,'current')
  assert.equal(progress.nodes.at(-1).caption,'部分入库，待续收')
  assert.match(progress.summary,/已入库数量可使用/)
})


test('多次执行节点使用最近事件，部分冲销后关闭后续入库提示',()=>{
  // 原批准与历次执行保持历史事实，业务关闭另由冲销状态表达。
  const record={document_type:'WarehouseInbound',business_status:'partially_posted',intent:'execute',
    status:'approved',generation:1,version:4,current_step:1,steps:[{name:'批准',role:null}],
    events:[{id:1,generation:1,action:'execute'},{id:2,generation:1,action:'execute'}]}
  assert.equal(documentApprovalProgress(record).nodes.at(-1).event.id,2)
  const closed=documentApprovalProgress({...record,business_status:'reversed'})
  assert.equal(closed.label,'已冲销')
  assert.equal(closed.nodes.at(-1).state,'withdrawn')
  assert.match(closed.summary,/不能继续入库/)
})
