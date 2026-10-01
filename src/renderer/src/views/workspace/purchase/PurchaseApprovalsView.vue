<script setup lang="ts">
import { computed,onMounted,ref,watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NSwitch } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import {usePiniaAppStore} from '../../../store/app-store'
import type {PurchaseApprovalRule,PurchaseApprovalPolicy} from '../../../../../shared/erp-api'
const store=usePiniaAppStore()
const {purchaseApprovalPolicy:policy,busy,error,user,connectionLost}=storeToRefs(store)
const form=ref<PurchaseApprovalPolicy & {reason:string}>({version:0,enabled:false,rules:[],reason:''})
const delegate=ref({request_id:0,approver_id:0,profile_version:0,reason:''})
const requestId=ref(0)
const admin=computed(()=>user.value?.roles.includes('admin')===true)
const rulesColumns=[{key:'department',title:'部门（空白适用所有部门）'},{key:'minimum',title:'金额下限（含）'},{key:'maximum',title:'金额上限（不含；空白无上限）'},{key:'steps',title:'审批顺序'},{key:'actions',title:'操作'}]
watch(policy,value=>{if(value)form.value={version:value.version,enabled:value.enabled,rules:value.rules.map(rule=>({...rule,steps:rule.steps.map(step=>({...step}))})),reason:''}})
watch(()=>user.value?.id,()=>{policy.value=null;form.value={version:0,enabled:false,rules:[],reason:''};delegate.value={request_id:0,approver_id:0,profile_version:0,reason:''}})
let ticket=0
watch(()=>delegate.value.request_id,async id=>{
  const current=++ticket;if(!id)return
  try{const result=await store.queryDataset({dataset:'purchaseRequests',query:'',page:1,page_size:1,filters:{id}});if(current===ticket)delegate.value.profile_version=Number(result.items[0]?.version??0)}catch{delegate.value.profile_version=0}
})
onMounted(()=>{void store.loadPurchaseApprovalPolicy()})
function addRule():void{form.value.rules.push({department:'',minimum:'0.00',maximum:null,steps:[{role_code:'',approver_id:null}]})}
function removeRule(row:PurchaseApprovalRule):void{form.value.rules.splice(form.value.rules.indexOf(row),1)}
async function save():Promise<void>{await store.savePurchaseApprovalPolicy({version:form.value.version,enabled:form.value.enabled,reason:form.value.reason,rules:form.value.rules.map(rule=>({...rule,maximum:rule.maximum?.trim()||null,steps:rule.steps.map(step=>({...step,approver_id:step.approver_id||null}))}))})}
</script>
<template>
  <section class="page-header"><h1>采购审批规则</h1><p>提交申请时按部门及预计金额固定审批链。部门规则优先于通用规则，金额上限不包含边界；在途申请继续使用原规则。申请人、提交人及同轮已审批人不能占用下一个审批节点。</p></section>
  <p v-if="error" role="alert">{{error}}</p>
  <form v-if="admin" class="card" @submit.prevent="save"><div class="form-grid"><label>启用分级审批<NSwitch v-model:value="form.enabled" :disabled="busy" /></label><label>规则修改原因<AppInput v-model.trim="form.reason" required maxlength="200" /></label></div>
    <WorkspaceTable title="审批金额与岗位规则" :data="form.rules" :columns="rulesColumns" :min-table-width="1300">
      <template #cell-department="{row}"><AppInput v-model.trim="row.department" maxlength="80" /></template>
      <template #cell-minimum="{row}"><AppInput v-model="row.minimum" required inputmode="decimal" /></template>
      <template #cell-maximum="{row}"><AppInput v-model="row.maximum" inputmode="decimal" placeholder="无上限" /></template>
      <template #cell-steps="{row}"><div v-for="(step,index) in row.steps" :key="index" class="form-grid"><label>第 {{index+1}} 级岗位<WorkspaceSelect v-model="step.role_code" remote-dataset="roles" :options="[{value:'',label:'选择审批岗位',disabled:true}]" required /></label><label>指定人员（选填）<WorkspaceSelect :model-value="step.approver_id??0" remote-dataset="users" :options="[{value:0,label:'该岗位任一审批人'}]" @update:model-value="id=>{step.approver_id=id||null}" /></label><AppButton type="button" variant="text" :disabled="row.steps.length===1" @click="row.steps.splice(index,1)">移除节点</AppButton></div><AppButton type="button" variant="secondary" :disabled="row.steps.length>=10" @click="row.steps.push({role_code:'',approver_id:null})">添加下一级</AppButton></template>
      <template #cell-actions="{row}"><AppButton type="button" variant="text" @click="removeRule(row)">移除规则</AppButton></template>
    </WorkspaceTable>
    <div class="form-actions"><AppButton type="button" variant="secondary" :disabled="form.rules.length>=50" @click="addRule">添加金额规则</AppButton><AppButton type="submit" :disabled="busy||connectionLost">保存审批规则</AppButton><AppButton type="button" variant="secondary" :disabled="busy" @click="store.loadPurchaseApprovalPolicy()">重新读取</AppButton></div>
  </form>
  <p v-else>当前{{policy?.enabled?'已启用':'未启用'}}分级审批。规则由管理员维护；未启用时保留原有单级审批方式。</p>
  <form v-if="admin" class="card" @submit.prevent="store.delegatePurchaseApproval({...delegate})"><h2>指定临时代审</h2><div class="form-grid"><label>在途采购申请<WorkspaceSelect v-model="delegate.request_id" remote-dataset="purchaseRequests" :remote-filters="{status:'submitted'}" :options="[{value:0,label:'选择申请',disabled:true}]" required /></label><label>代审人<WorkspaceSelect v-model="delegate.approver_id" remote-dataset="users" :remote-filters="{is_active:true}" :options="[{value:0,label:'选择具备审批权限的账号',disabled:true}]" required /></label><label>代审原因<AppInput v-model.trim="delegate.reason" required maxlength="200" /></label></div><AppButton type="submit" :disabled="busy||connectionLost||!delegate.profile_version">保存代审</AppButton></form>
  <WorkspaceTable title="采购审批历史" dataset="purchaseApprovalHistory" :columns="[{key:'request_id',title:'申请编号'},{key:'action',title:'操作'},{key:'reason',title:'原因'},{key:'created_by',title:'操作账号'},{key:'created_at',title:'时间'},{key:'evidence_json',title:'审批证据'}]" :data="[]" :min-table-width="1100" />
  <label>查看审批链<WorkspaceSelect v-model="requestId" remote-dataset="purchaseRequests" :options="[{value:0,label:'选择采购申请'}]" /></label>
  <WorkspaceTable v-if="requestId" title="申请审批节点" dataset="purchaseApprovalStages" :query-filters="{request_id:requestId}" :columns="[{key:'round',title:'轮次'},{key:'position',title:'顺序'},{key:'role_code',title:'审批岗位'},{key:'approver_id',title:'指定账号'},{key:'status',title:'状态'},{key:'reviewed_by',title:'审批账号'},{key:'reviewed_at',title:'审批时间'}]" :data="[]" />
</template>
