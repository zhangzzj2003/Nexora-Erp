<script setup lang="ts">
import { computed,ref,watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { ProductionToolAction,TableRow } from '../../../../../shared/erp-api'
const store=usePiniaAppStore()
const {productionToolResult:result,busy,error,connectionLost,user}=storeToRefs(store)
const action=ref<ProductionToolAction>('mrp')
const options:{value:ProductionToolAction;label:string}[]=[{value:'mrp',label:'计算物料缺口'},{value:'create_request',label:'缺料转采购申请'},{value:'policy',label:'安全库存与提前期'},{value:'create_center',label:'新增工作中心'},{value:'schedule',label:'安排生产工序'},{value:'cancel_schedule',label:'取消排程'},{value:'quality',label:'不合格品处置'},{value:'wip',label:'截止日在制成本'}]
const form=ref({warehouse_id:1,through_date:'',material_id:0,safety_quantity:'0',lead_days:0,version:0,name:'',id:0,work_order_id:0,center_id:0,operation:'',starts_at:'',ends_at:'',completion_id:0,kind:'scrap',quantity:'1',reason:'',replacement_id:0,replacement_quantity:'1'})
const titles:Record<string,string>={material_id:'物料编号',warehouse_id:'仓库',sku:'物料编码',name:'物料／中心名称',unit:'单位',gross_quantity:'总需求',stock_quantity:'现有库存',incoming_quantity:'已确认在途',requested_quantity:'申请未转数量',safety_quantity:'安全库存',shortage_quantity:'净缺口',need_date:'需求日期',suggested_release_date:'建议下达日期',sources:'需求单据',id:'编号',version:'资料版本',lead_days:'提前天数',request_id:'采购申请编号',material_count:'物料种类',status:'状态',work_order_id:'工单编号',center_id:'工作中心',operation:'工序',starts_at:'开始时间（UTC）',ends_at:'结束时间（UTC）',completion_id:'完工单编号',kind:'处置类型',quantity:'数量',rework_order_id:'返工工单',reason:'处理原因',created_by:'操作账号',created_at:'建立时间',through_date:'截止日期',accumulated_amount:'累计生产成本',finished_amount:'已转合格品成本',quality_amount:'已转报废／返工成本',carried_amount:'承接返工成本',wip_amount:'在制余额',unpriced_count:'缺价项'}
const columns=computed(()=>result.value?.columns.map(item=>({...item,title:titles[item.key]??item.title}))??[])
const permission=computed(()=>action.value==='quality'?'production_completion.inspect':action.value==='wip'?'production_cost.view':action.value==='mrp'?'production.view':'work_order.create')
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{result.value=null;form.value.reason=''}, {flush:'sync'})
watch(action,()=>{result.value=null})
let policyTicket=0
watch(()=>[form.value.material_id,form.value.warehouse_id],async()=>{
  if(action.value!=='policy'||!form.value.material_id)return
  const ticket=++policyTicket
  try{const page=await store.queryDataset({dataset:'planningPolicies',query:'',page:1,page_size:1,filters:{material_id:form.value.material_id,warehouse_id:form.value.warehouse_id}})
    if(ticket!==policyTicket)return
    const row=page.items[0];form.value.version=Number(row?.version??0);form.value.safety_quantity=String(row?.safety_quantity??'0');form.value.lead_days=Number(row?.lead_days??0)
  }catch{form.value.version=0}
})
async function run():Promise<void>{
  if(!store.can(permission.value)||connectionLost.value)return
  const f=form.value;let payload:Record<string,unknown>={}
  if(['mrp','create_request','wip'].includes(action.value))payload={warehouse_id:f.warehouse_id,through_date:f.through_date}
  else if(action.value==='policy')payload={warehouse_id:f.warehouse_id,material_id:f.material_id,safety_quantity:f.safety_quantity,lead_days:f.lead_days,version:f.version,reason:f.reason}
  else if(action.value==='create_center')payload={name:f.name,reason:f.reason}
  else if(action.value==='schedule'){
    const start=new Date(f.starts_at.replace(' ','T')),end=new Date(f.ends_at.replace(' ','T'))
    if(!Number.isFinite(start.getTime())||!Number.isFinite(end.getTime())){error.value='请选择完整的开始和结束时间';return}
    payload={...f.id?{id:f.id,version:f.version}:{},work_order_id:f.work_order_id,center_id:f.center_id,operation:f.operation,starts_at:start.toISOString(),ends_at:end.toISOString(),reason:f.reason}
  }else if(action.value==='cancel_schedule')payload={id:f.id,reason:f.reason}
  else payload={completion_id:f.completion_id,kind:f.kind,quantity:f.quantity,reason:f.reason,replacements:f.kind==='rework'&&f.replacement_id?[{component_material_id:f.replacement_id,quantity:f.replacement_quantity}]:[]}
  await store.runProductionTool(action.value,payload)
}
function editSchedule(row:TableRow):void{
  action.value='schedule';form.value.id=Number(row.id);form.value.version=Number(row.version);form.value.work_order_id=Number(row.work_order_id);form.value.center_id=Number(row.center_id);form.value.operation=String(row.operation)
  const display=(value:unknown)=>{const date=new Date(String(value));const parts=[date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')];return `${parts.join('-')} ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`}
  form.value.starts_at=display(row.starts_at);form.value.ends_at=display(row.ends_at)
}
</script>
<template>
  <section class="page-header"><h1>生产计划与质量</h1><p>根据已确认销售及工单需求计算缺料，工作中心排程按时间检查冲突。不合格品留在质量记录中，不进入可用成品库存。</p></section>
  <form class="card" @submit.prevent="run"><div class="form-grid">
    <label>处理事项<WorkspaceSelect v-model="action" :options="options" :disabled="busy" /></label>
    <template v-if="['mrp','create_request','wip','policy'].includes(action)"><label>仓库<WorkspaceSelect v-model="form.warehouse_id" remote-dataset="warehouses" :options="[]" required /></label></template>
    <label v-if="['mrp','create_request','wip'].includes(action)">需求／截止日期<NDatePicker type="date" value-format="yyyy-MM-dd" :formatted-value="form.through_date||null" @update:formatted-value="value=>{form.through_date=typeof value==='string'?value:''}" /></label>
    <template v-if="action==='policy'"><label>物料<WorkspaceSelect v-model="form.material_id" remote-dataset="materials" :options="[{value:0,label:'选择物料',disabled:true}]" required /></label><label>安全库存<AppInput v-model="form.safety_quantity" inputmode="decimal" required /></label><label>提前天数<AppInput v-model.number="form.lead_days" type="number" min="0" max="3650" required /></label></template>
    <label v-if="action==='create_center'">工作中心名称<AppInput v-model.trim="form.name" required maxlength="80" /></label>
    <template v-if="action==='schedule'"><label>工单<WorkspaceSelect v-model="form.work_order_id" remote-dataset="workOrders" :options="[{value:0,label:'选择工单',disabled:true}]" required /></label><label>工作中心<WorkspaceSelect v-model="form.center_id" remote-dataset="workCenters" :options="[{value:0,label:'选择中心',disabled:true}]" required /></label><label>工序<AppInput v-model.trim="form.operation" required maxlength="80" /></label><label>开始时间<NDatePicker type="datetime" value-format="yyyy-MM-dd HH:mm" :formatted-value="form.starts_at||null" @update:formatted-value="value=>{form.starts_at=typeof value==='string'?value:''}" /></label><label>结束时间<NDatePicker type="datetime" value-format="yyyy-MM-dd HH:mm" :formatted-value="form.ends_at||null" @update:formatted-value="value=>{form.ends_at=typeof value==='string'?value:''}" /></label></template>
    <label v-if="action==='cancel_schedule'">排程编号<AppInput v-model.number="form.id" type="number" min="1" required /></label>
    <template v-if="action==='quality'"><label>完工单<WorkspaceSelect v-model="form.completion_id" remote-dataset="productionCompletions" :remote-filters="{status:'posted'}" :options="[{value:0,label:'选择已确认完工单',disabled:true}]" required /></label><label>处置方式<WorkspaceSelect v-model="form.kind" :options="[{value:'scrap',label:'报废'},{value:'rework',label:'返工'}]" /></label><label>处置数量<AppInput v-model="form.quantity" required inputmode="decimal" /></label><template v-if="form.kind==='rework'"><label>替换料（选填）<WorkspaceSelect v-model="form.replacement_id" remote-dataset="materials" :options="[{value:0,label:'无需替换料'}]" /></label><label v-if="form.replacement_id">替换料总需求<AppInput v-model="form.replacement_quantity" required inputmode="decimal" /></label></template></template>
    <label v-if="!['mrp','create_request','wip'].includes(action)">处理原因<AppInput v-model.trim="form.reason" required maxlength="200" /></label>
  </div><div class="form-actions"><AppButton type="submit" :disabled="busy||connectionLost||!store.can(permission)">{{ busy?'处理中…':['mrp','wip'].includes(action)?'查询':'保存处理' }}</AppButton><AppButton v-if="action==='schedule'&&form.id" type="button" variant="secondary" @click="form.id=0;form.version=0">改为新增排程</AppButton></div><p v-if="error" role="alert">{{ error }}</p></form>
  <p v-if="action==='mrp'||action==='create_request'" class="muted">销售未分配部分按最新启用 BOM 展开；已有工单按需料快照计算。扣除本仓库存、公司已确认采购在途及申请未转数量；建议日期供人工核对，不保证供应商交期。</p>
  <p v-if="action==='wip'" class="muted">按截止日业务范围及现有核价重算。在制余额扣除已结算的成品、报废和返工转出成本，未完成成本结算的完工仍保留待核对金额。</p>
  <WorkspaceTable v-if="result" title="处理结果" :snapshot-id="result.snapshot_id" :columns="columns" :data="result.rows" :min-table-width="1200" />
  <WorkspaceTable title="生产排程" dataset="productionSchedules" :columns="[{key:'id',title:'排程编号'},{key:'work_order_id',title:'工单'},{key:'center_id',title:'中心'},{key:'operation',title:'工序'},{key:'starts_at',title:'开始（UTC）'},{key:'ends_at',title:'结束（UTC）'},{key:'status',title:'状态'},{key:'edit',title:'操作'}]" :data="[] as TableRow[]" :min-table-width="1100"><template #cell-edit="{row}"><AppButton v-if="store.can('work_order.create')" variant="text" @click="editSchedule(row)">编辑排程</AppButton></template></WorkspaceTable>
  <WorkspaceTable title="质量处置" dataset="qualityDispositions" :columns="[{key:'id',title:'处置编号'},{key:'completion_id',title:'原完工单'},{key:'kind',title:'方式'},{key:'quantity',title:'数量'},{key:'rework_order_id',title:'返工工单'},{key:'reason',title:'原因'}]" :data="[]" />
</template>
