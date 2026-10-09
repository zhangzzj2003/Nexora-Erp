// 测试与隔离浏览器预览共用示例状态；所有业务写入仅修改内存，不连接真实服务。
export const inboundFlowStoreSource = `
import {defineStore} from 'pinia'
import {ref} from 'vue'
import {createAppState} from '/src/renderer/src/store/state.ts'
export const fixture={fail:false,calls:[]}
export const usePiniaAppStore=defineStore('inbound-flow-ui',()=>{
 const state=createAppState()
 state.user.value={id:1,username:'demo',roles:['admin'],permissions:['other_inbound.post','other_inbound.create','other_inbound.cancel','other_inbound.reverse']}
 state.roles.value=[{code:'admin',label:'管理员'}]
 state.otherInbounds.value=[{id:1,document_no:'QTRK-20261009-000001',status:'draft',approval:{status:'draft'},reason:'gift',
  warehouse_id:1,warehouse_name:'主仓库',note:'按本次实际到货数量办理入库',reference:'',created_by_name:'示例管理员',created_at:'2026-10-09T07:30:00Z',reversal_id:null,
  lines:[['EL-CN-000001','示例 · 2.54mm 排针 8P','1000','条'],['EL-CN-000002','示例 · 接线端子 2P','1000','个'],['EL-CR-000001','示例 · 8MHz 晶振','2000','个']].map(([sku,material_name,quantity,unit],index)=>({id:index+7,material_id:index+1,sku,material_name,quantity,unit,received_quantity:'0',remaining_quantity:quantity,physical_lots:[]}))}]
 function recordFor(target){
  const inbound=state.otherInbounds.value.find(item=>item.id===target.document_id)
  const status=(target.intent==='reverse'?inbound.reversal_approval:inbound.approval)?.status??'draft'
  return {...target,document_no:inbound.document_no,business_status:inbound.status,status,version:1,generation:1,
   current_step:status==='approved'||status==='executed'?1:0,steps:[{name:'批准',role:null,action:'approve'}],events:[],
   content_matches:true,can_submit:['draft','rejected','withdrawn'].includes(status)&&inbound.status==='draft',can_review:status==='submitted',
   can_withdraw:['submitted','approved'].includes(status)&&inbound.status==='draft',summary:[],reversal_reason:target.intent==='reverse'?'重复入库':''}
 }
 async function openDocumentApproval(target){
  fixture.calls.push(['open',target]);state.documentApprovalTarget.value=target
  state.documentApprovalRecord.value=recordFor(target);return true
 }
 async function loadDocumentApproval(){
  fixture.calls.push(['refresh']);if(state.documentApprovalTarget.value)state.documentApprovalRecord.value=recordFor(state.documentApprovalTarget.value)
 }
 function closeDocumentApproval(){state.documentApprovalTarget.value=null;state.documentApprovalRecord.value=null}
 async function actDocumentApproval(action){
  fixture.calls.push([action]);if(state.connectionLost.value||state.busy.value)return false
  const target=state.documentApprovalTarget.value,record=state.documentApprovalRecord.value
  if(!record||!(action==='submit'?record.can_submit:action==='withdraw'?record.can_withdraw:record.can_review))return false
  if(fixture.fail){state.documentApprovalError.value='模拟审批失败';return false}
  const inbound=state.otherInbounds.value.find(item=>item.id===target.document_id)
  inbound[target.intent==='reverse'?'reversal_approval':'approval']={status:{submit:'submitted',approve:'approved',reject:'rejected',withdraw:'withdrawn'}[action]}
  state.documentApprovalRecord.value=recordFor(target);return true
 }
 async function postOtherInbound(id,lines){
  fixture.calls.push(['post',id,lines]);state.error.value=''
  if(fixture.fail){state.error.value='模拟保存失败，请重试';return}
  const inbound=state.otherInbounds.value.find(item=>item.id===id)
  for(const line of inbound.lines){
   const input=lines?.find(item=>item.inbound_line_id===line.id)
   const quantity=lines?(input?.lots.reduce((sum,part)=>sum+Number(part.quantity),0)??0):Number(line.remaining_quantity)
   line.received_quantity=String(Number(line.received_quantity)+quantity)
   line.remaining_quantity=String(Number(line.quantity)-Number(line.received_quantity))
  }
  inbound.status=inbound.lines.every(line=>line.remaining_quantity==='0')?'posted':'partially_posted'
  if(inbound.status==='posted')inbound.approval={status:'executed'}
 }
 return {...state,can:key=>state.user.value?.permissions.includes(key)??false,localTime:value=>value,
  openDocumentApproval,closeDocumentApproval,loadDocumentApproval,actDocumentApproval,postOtherInbound,
  subscribeMaterialSupply(){return()=>{}},async loadMaterialSupply(){},
  createOtherInbound(){},cancelOtherInbound(){},reverseOtherInbound(){},prepareOtherInboundReopen(){return false}}
})
`
