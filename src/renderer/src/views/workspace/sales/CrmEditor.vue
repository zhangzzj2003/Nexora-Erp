<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NInputNumber } from 'naive-ui'
import type { CrmKind } from '../../../../../shared/crm-api'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import CrmDate from './CrmDate.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { crmFormError, crmKindLabel, crmStageLabel } from './crm-display'

// 同一表单可在页内或弹窗使用，校验、修订原因及保存逻辑保持一致。
const props=withDefaults(defineProps<{kind: CrmKind;dialog?:boolean}>(),{dialog:false})
const emit=defineEmits<{saved:[];close:[];createOpportunity:[]}>()
const store=usePiniaAppStore()
const {crmForms:forms,crmEdit:edits,crmOptions:options,crmOverview:overview,busy,connectionLost,crmLoading:loading,error}=storeToRefs(store)
const edit=computed(()=>edits.value[props.kind])
const failure=ref('')
const disabled=computed(()=>busy.value || loading.value || connectionLost.value || !options.value)
const customer=computed(()=>props.kind==='quote' ? overview.value?.opportunities.find(item=>item.id===forms.value.quote.opportunity_id)?.customer_id ?? 0 : forms.value[props.kind].customer_id)
const customers=computed(()=>[{label:'选择客户',value:0,disabled:true},...(options.value?.customers??[]).map(row=>({label:row.name,value:row.id}))])
const owners=computed(()=>[{label:'选择负责人',value:0,disabled:true},...(options.value?.owners??[]).map(row=>({label:row.name,value:row.id}))])
const contacts=computed(()=>[{label:'未指定联系人',value:null},...(overview.value?.contacts??[]).filter(row=>row.customer_id===customer.value && row.is_active).map(row=>({label:row.name,value:row.id}))])
const opportunities=computed(()=>[{label:props.kind==='quote'?'选择开放商机':'不关联商机',value:props.kind==='quote'?0:null,disabled:props.kind==='quote'},
  ...(overview.value?.opportunities??[]).filter(row=>props.kind==='quote' ? !['won','lost'].includes(row.stage) : row.customer_id===customer.value).map(row=>({label:`${row.title} · ${row.customer_name}`,value:row.id}))])
const materials=computed(()=>[{label:'选择物料',value:0,disabled:true},...(options.value?.materials??[]).map(row=>({label:`${row.sku} · ${row.name}`,value:row.id}))])
const isEdit=computed(()=>!!edit.value)
watch(customer,()=>{
  if(props.kind==='contact')return
  const form=forms.value[props.kind]
  if(!contacts.value.some(row=>row.value===form.contact_id))form.contact_id=null
  if(props.kind==='activity' && !opportunities.value.some(row=>row.value===forms.value.activity.opportunity_id))forms.value.activity.opportunity_id=null
})
watch(()=>props.kind,()=>{failure.value=''})
async function save(): Promise<void> {
  failure.value=crmFormError(props.kind,forms.value)
  if(isEdit.value && !edit.value?.reason.trim())failure.value='请填写修订原因，原版本会保留。'
  if(failure.value || disabled.value)return
  if(await store.saveCrm(props.kind))emit('saved')
}
</script>
<template>
  <section class="crm-editor" :class="dialog ? 'crm-editor--dialog' : 'card'" :aria-label="`${isEdit ? '修订' : '新建'}${crmKindLabel[kind]}`">
    <div v-if="!dialog" class="section-heading"><h2>{{ isEdit ? '修订' : '新建' }}{{ crmKindLabel[kind] }}</h2><AppButton :disabled="busy" @click="emit('close')">返回列表</AppButton></div>
    <p v-if="kind==='quote'">人民币报价不含税费和折扣计算。提交时固定客户、联系人和物料资料；之后须由未参与编制的账号独立审核。</p>
    <p v-if="kind==='quote' && opportunities.length===1 && !isEdit">暂无开放商机，须先建立销售商机才能编制报价。<AppButton v-if="store.can('crm_opportunity.manage')" variant="text" :disabled="disabled" @click="emit('createOpportunity')">建立销售商机</AppButton></p>
    <p v-else-if="kind==='opportunity'">逐条填写成交概率；留空表示未评估，不计入加权预测。预估金额和预测金额不代表订单、收入或收款。“已转单”由批准报价转订单后自动登记。</p>
    <p v-else-if="kind==='activity'">这里只登记待办和实际跟进结果，不会发送邮件、短信或提醒。结束后原记录保留，更正可另建跟进。</p>
    <form @submit.prevent="save">
      <div v-if="kind==='contact'" class="form-grid">
        <label>客户<WorkspaceSelect v-model="forms.contact.customer_id" :options="customers" required :disabled="disabled || isEdit" /></label>
        <label>联系人姓名<AppInput v-model.trim="forms.contact.name" required maxlength="120" :disabled="disabled" /></label>
        <label>职务<AppInput v-model.trim="forms.contact.job_title" maxlength="120" :disabled="disabled" /></label>
        <label>电话<AppInput v-model.trim="forms.contact.phone" maxlength="80" :disabled="disabled" /></label>
        <label>邮箱<AppInput v-model.trim="forms.contact.email" maxlength="160" :disabled="disabled" /></label>
        <label>联系人状态<WorkspaceSelect v-model="forms.contact.is_active" :options="[{label:'启用',value:true},{label:'停用',value:false}]" :disabled="disabled" /></label>
        <label class="crm-wide">备注<AppInput v-model.trim="forms.contact.note" maxlength="1000" :disabled="disabled" /></label>
      </div>
      <div v-else-if="kind==='activity'" class="form-grid">
        <label>客户<WorkspaceSelect v-model="forms.activity.customer_id" :options="customers" required :disabled="disabled" /></label>
        <label>联系人<WorkspaceSelect v-model="forms.activity.contact_id" :options="contacts" :disabled="disabled" /></label>
        <label>关联商机<WorkspaceSelect v-model="forms.activity.opportunity_id" :options="opportunities" :disabled="disabled" /></label>
        <label>跟进事项<AppInput v-model.trim="forms.activity.subject" required maxlength="160" :disabled="disabled" /></label>
        <label>负责人<WorkspaceSelect v-model="forms.activity.owner_id" :options="owners" required :disabled="disabled" /></label>
        <label>跟进期限<CrmDate v-model="forms.activity.due_date" :disabled="disabled" /></label>
        <label class="crm-wide">跟进安排<AppInput v-model.trim="forms.activity.note" maxlength="1000" :disabled="disabled" /></label>
      </div>
      <div v-else-if="kind==='opportunity'" class="form-grid">
        <label>客户<WorkspaceSelect v-model="forms.opportunity.customer_id" :options="customers" required :disabled="disabled || isEdit" /></label>
        <label>联系人<WorkspaceSelect v-model="forms.opportunity.contact_id" :options="contacts" :disabled="disabled" /></label>
        <label>商机名称<AppInput v-model.trim="forms.opportunity.title" required maxlength="160" :disabled="disabled" /></label>
        <label>负责人<WorkspaceSelect v-model="forms.opportunity.owner_id" :options="owners" required :disabled="disabled" /></label>
        <label>商机阶段<WorkspaceSelect v-model="forms.opportunity.stage" :options="Object.entries(crmStageLabel).filter(([key])=>key!=='won' && (isEdit || key!=='lost')).map(([value,label])=>({value,label}))" :disabled="disabled || (isEdit && forms.opportunity.stage==='lost')" /></label>
        <label>预计成交日<CrmDate v-model="forms.opportunity.expected_close_date" :disabled="disabled" /></label>
        <label>预估金额（元）<AppInput v-model.trim="forms.opportunity.estimated_amount" type="number" min="0" max="100000000000" step="0.01" required :disabled="disabled" /></label>
        <label>成交概率（%）<NInputNumber v-model:value="forms.opportunity.probability_percent" :min="0" :max="100" :precision="0" clearable placeholder="未评估" :disabled="disabled" /></label>
        <label>商机说明<AppInput v-model.trim="forms.opportunity.note" maxlength="1000" :disabled="disabled" /></label>
      </div>
      <template v-else>
        <div class="form-grid">
          <label>所属商机<WorkspaceSelect v-model="forms.quote.opportunity_id" :options="opportunities" required :disabled="disabled || isEdit" /></label>
          <label>报价编号<AppInput v-model.trim="forms.quote.reference" required maxlength="100" :disabled="disabled" /></label>
          <label>联系人<WorkspaceSelect v-model="forms.quote.contact_id" :options="contacts" :disabled="disabled" /></label>
          <label>报价有效期<CrmDate v-model="forms.quote.valid_until" :disabled="disabled" /></label>
          <label class="crm-wide">交货及商务条款<AppInput v-model.trim="forms.quote.terms" maxlength="1000" :disabled="disabled" /></label>
        </div>
        <h3>报价明细</h3>
        <div v-for="(line,index) in forms.quote.lines" :key="index" class="crm-quote-line">
          <label>物料 {{ index+1 }}<WorkspaceSelect v-model="line.material_id" :options="materials" required :disabled="disabled" /></label>
          <label>数量 {{ index+1 }}<AppInput v-model.trim="line.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="disabled" /></label>
          <label>单价 {{ index+1 }}（元）<AppInput v-model.trim="line.unit_price" type="number" min="0" max="1000000000" step="0.0001" required :disabled="disabled" /></label>
          <AppButton :disabled="disabled || forms.quote.lines.length===1" :aria-label="`删除报价第 ${index+1} 行`" @click="forms.quote.lines.splice(index,1)">删除行</AppButton>
        </div>
        <AppButton :disabled="disabled || forms.quote.lines.length>=100" @click="forms.quote.lines.push({material_id:0,quantity:'1',unit_price:'0'})">增加明细</AppButton>
      </template>
      <label v-if="isEdit && edit">修订原因<AppInput v-model.trim="edit.reason" required maxlength="500" :disabled="disabled" /></label>
      <p v-if="failure" role="alert">{{ failure }}</p>
      <p v-if="error" role="alert">{{ error }} 输入及修订原因已保留，请修正后重试；版本冲突时先重新读取记录。</p>
      <div class="crm-toolbar"><AppButton v-if="dialog" type="button" :disabled="busy" @click="emit('close')">取消</AppButton>
        <AppButton type="submit" variant="primary" :disabled="disabled">{{ busy ? '正在保存…' : isEdit ? '保存修订' : `保存${crmKindLabel[kind]}` }}</AppButton>
        <span v-if="!options?.customers.length" class="muted">暂无客户资料。</span><AppButton v-if="store.can('customer.manage')" variant="text" :disabled="busy" @click="store.navigateToRoute('customers')">前往客户资料</AppButton></div>
    </form>
  </section>
</template>
<style scoped>
/* 弹窗传送到 body 后不再位于 CRM 页内，局部样式保证表单间距及窄窗布局。 */
.crm-editor--dialog form { display: grid; gap: 18px; }
.crm-editor--dialog .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.crm-editor--dialog .crm-wide { grid-column: 1 / -1; }
.crm-editor--dialog .crm-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
@media (max-width: 650px) {
  .crm-editor--dialog .form-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
