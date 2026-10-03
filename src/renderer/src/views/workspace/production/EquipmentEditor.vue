<script setup lang="ts">
import {computed,ref} from 'vue'
import {storeToRefs} from 'pinia'
import {NCheckbox,NDatePicker} from 'naive-ui'
import type {EquipmentEntity} from '../../../../../shared/equipment-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import {datePickerString,dateOutsideRange,vDateField} from '../../../utils/date-field'
const props=defineProps<{kind:EquipmentEntity}>(),emit=defineEmits<{saved:[];close:[]}>(),store=usePiniaAppStore()
const {equipmentForms:forms,equipmentEdit:edit,equipmentOverview:overview,busy,error,connectionLost}=storeToRefs(store)
const disabled=computed(()=>busy.value || connectionLost.value)
const label=computed(()=>props.kind==='asset'?'设备档案':props.kind==='plan'?'日历计划':props.kind==='hour_plan'?'运行小时计划':'维护工单')
const planMode=ref<'calendar'|'hours'>(forms.value.job.hour_plan_id?'hours':'calendar')
const equipment=computed(()=>[{label:'选择设备',value:0,disabled:true},...(overview.value?.equipment??[]).map(row=>({label:`${row.code} · ${row.name}`,value:row.id,
  disabled:row.status!=='active' && (props.kind==='job' || (props.kind==='hour_plan'?forms.value.hour_plan.enabled:forms.value.plan.enabled))}))])
const plans=computed(()=>[{label:'选择周期计划',value:null,disabled:true},...(overview.value?.plans??[]).filter(row=>row.equipment_id===forms.value.job.equipment_id).map(row=>({label:`${row.reference} · ${row.title} · ${row.next_due}`,value:row.id,disabled:!row.enabled || (!edit.value && row.open_job_ids.length>0)}))])
const hourPlans=computed(()=>[{label:'选择运行小时计划',value:null,disabled:true},...(overview.value?.hour_plans??[]).filter(row=>row.equipment_id===forms.value.job.equipment_id)
  .map(row=>({label:`${row.reference} · ${row.title} · ${row.next_due_hours} 小时`,value:row.id,
    disabled:!row.enabled || (!edit.value && row.open_job_ids.length>0)}))])
const executors=computed(()=>[{label:'选择启用的执行人',value:0,disabled:true},...(overview.value?.executors??[]).map(row=>({label:row.username,value:row.id}))])
const warehouses=computed(()=>[{label:'选择耗材仓库',value:null,disabled:true},...(overview.value?.warehouses??[]).map(row=>({label:row.name,value:row.id}))])
const materials=computed(()=>[{label:'选择耗材',value:0,disabled:true},...(overview.value?.materials??[]).map(row=>({label:`${row.sku} · ${row.name} · ${row.unit}`,value:row.id}))])
const orders=computed(()=>[{label:'不关联生产工单',value:null},...(overview.value?.work_orders??[]).map(row=>({label:`生产工单 #${row.id}`,value:row.id}))])
async function save():Promise<void>{if(await store.saveEquipmentRecord(props.kind))emit('saved')}
function clearPlans():void{forms.value.job.plan_id=null;forms.value.job.hour_plan_id=null}
</script>
<template>
  <section class="equipment-editor" :aria-label="`编制${label}`">
    <div class="equipment-toolbar"><h2>{{ edit?'修订':'新建' }}{{ label }}</h2><AppButton :disabled="busy" @click="emit('close')">返回记录</AppButton></div>
    <p v-if="edit">正在修订 #{{ edit.id }} · 旧版本 v{{ edit.version }}。发生冲突时保留本次输入，须核对最新证据后重新修订。</p>
    <form @submit.prevent="save">
      <div v-if="kind==='asset'" class="form-grid">
        <label>设备编号<AppInput v-model.trim="forms.asset.code" pattern="[A-Za-z0-9_-]{1,40}" maxlength="40" required :disabled="disabled" /></label>
        <label>设备名称<AppInput v-model.trim="forms.asset.name" maxlength="100" required :disabled="disabled" /></label>
        <label>序列号（选填）<AppInput v-model.trim="forms.asset.serial_number" maxlength="80" :disabled="disabled" /></label>
        <label>设备位置<AppInput v-model.trim="forms.asset.location" maxlength="120" required :disabled="disabled" /></label>
        <label>设备状态<WorkspaceSelect v-model="forms.asset.status" :options="[{label:'启用',value:'active'},{label:'停用',value:'inactive'},{label:'报废',value:'retired'}]" :disabled="disabled" /></label>
        <p class="equipment-wide">未结束工单阻止改绑编号和序列号。停用或报废前须结束工单、停用所有保养计划；报废不能重新启用。</p>
        <label class="equipment-wide">档案建立或修订原因<AppInput v-model.trim="forms.asset.reason" maxlength="200" required :disabled="disabled" /></label>
      </div>
      <div v-else-if="kind==='plan'" class="form-grid">
        <label>计划设备<WorkspaceSelect v-model="forms.plan.equipment_id" :options="equipment" required :disabled="disabled" /></label>
        <label>计划依据编号<AppInput v-model.trim="forms.plan.reference" maxlength="100" required :disabled="disabled" /></label>
        <label class="equipment-wide">保养内容<AppInput v-model.trim="forms.plan.title" maxlength="120" required :disabled="disabled" /></label>
        <label>间隔天数<AppInput v-model.number="forms.plan.interval_days" type="number" min="1" max="3650" step="1" required :disabled="disabled" /></label>
        <label>下次到期日<NDatePicker v-date-field="{required:true,min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="forms.plan.next_due || null" :is-date-disabled="(stamp:number)=>dateOutsideRange(stamp,'2000-01-01','2099-12-31')" :disabled="disabled" @update:formatted-value="value=>forms.plan.next_due=datePickerString(value)" /></label>
        <NCheckbox v-model:checked="forms.plan.enabled" :disabled="disabled">启用周期计划</NCheckbox>
        <p class="equipment-wide">按服务端 UTC 日期判断到期。验收后以验收日期加间隔天数推进；已有未结束工单时不能修订计划。</p>
        <label class="equipment-wide">计划建立或修订原因<AppInput v-model.trim="forms.plan.reason" maxlength="200" required :disabled="disabled" /></label>
      </div>
      <div v-else-if="kind==='hour_plan'" class="form-grid">
        <label>计划设备<WorkspaceSelect v-model="forms.hour_plan.equipment_id" :options="equipment" required :disabled="disabled" /></label>
        <label>计划依据编号<AppInput v-model.trim="forms.hour_plan.reference" maxlength="100" required :disabled="disabled" /></label>
        <label class="equipment-wide">保养内容<AppInput v-model.trim="forms.hour_plan.title" maxlength="120" required :disabled="disabled" /></label>
        <label>间隔运行小时<AppInput v-model="forms.hour_plan.interval_hours" type="number" min="0.01" max="1000000" step="0.01" required :disabled="disabled" /></label>
        <label>下次到期表计小时<AppInput v-model="forms.hour_plan.next_due_hours" type="number" min="0" max="1000000000" step="0.01" required :disabled="disabled" /></label>
        <NCheckbox v-model:checked="forms.hour_plan.enabled" :disabled="disabled">启用运行小时计划</NCheckbox>
        <p class="equipment-wide">先登记设备表计基线。最新读数达到阈值才可提交保养工单；验收后按当前读数与原阈值的较大者加间隔推进。</p>
        <label class="equipment-wide">计划建立或修订原因<AppInput v-model.trim="forms.hour_plan.reason" maxlength="200" required :disabled="disabled" /></label>
      </div>
      <template v-else>
        <div class="form-grid">
          <label>维护设备<WorkspaceSelect v-model="forms.job.equipment_id" :options="equipment" required :disabled="disabled" @change="clearPlans" /></label>
          <label>维护依据编号<AppInput v-model.trim="forms.job.reference" maxlength="100" required :disabled="disabled" /></label>
          <label>维护方式<WorkspaceSelect v-model="forms.job.kind" :options="[{label:'故障维修',value:'corrective'},{label:'周期保养',value:'preventive'}]" :disabled="disabled" @change="clearPlans" /></label>
          <label v-if="forms.job.kind==='preventive'">触发依据<WorkspaceSelect v-model="planMode" :options="[{label:'日历到期',value:'calendar'},{label:'运行小时到期',value:'hours'}]" :disabled="disabled" @change="clearPlans" /></label>
          <label v-if="forms.job.kind==='preventive' && planMode==='calendar'">日历计划<WorkspaceSelect v-model="forms.job.plan_id" :options="plans" required :disabled="disabled" /></label>
          <label v-if="forms.job.kind==='preventive' && planMode==='hours'">运行小时计划<WorkspaceSelect v-model="forms.job.hour_plan_id" :options="hourPlans" required :disabled="disabled" /></label>
          <label>指定执行人<WorkspaceSelect v-model="forms.job.assigned_to" :options="executors" required :disabled="disabled" /></label>
          <label v-if="store.can('production.view')">关联生产工单（选填）<WorkspaceSelect v-model="forms.job.work_order_id" :options="orders" :disabled="disabled" /></label>
          <label class="equipment-wide">维护要求或故障记录<AppInput v-model.trim="forms.job.request_note" maxlength="600" required :disabled="disabled" /></label>
        </div>
        <section aria-label="维护耗材">
          <div class="equipment-toolbar"><h3>本次耗材</h3><AppButton :disabled="disabled || forms.job.parts.length>=100" @click="forms.job.parts.push({material_id:0,quantity:'1'})">添加耗材</AppButton></div>
          <p>开始维护只生成出库草稿，仓库确认才扣库存。无耗材时保持为空。领取耗材的执行人须同时有其他出库建单权限。</p>
          <label v-if="forms.job.parts.length">耗材仓库<WorkspaceSelect v-model="forms.job.warehouse_id" :options="warehouses" required :disabled="disabled" /></label>
          <div v-for="(line,index) in forms.job.parts" :key="index" class="equipment-part">
            <label>耗材 {{ index+1 }}<WorkspaceSelect v-model="line.material_id" :options="materials" required :disabled="disabled" /></label>
            <label>本次总用量<AppInput v-model="line.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="disabled" /></label>
            <AppButton :disabled="disabled" :aria-label="`移除耗材 ${index+1}`" @click="forms.job.parts.splice(index,1)">移除</AppButton>
          </div>
        </section>
        <label>工单建立或修订原因<AppInput v-model.trim="forms.job.reason" maxlength="200" required :disabled="disabled" /></label>
        <p>草稿保存设备与计划版本快照，提交后正文固定。审核人须独立于编制、修订或提交人，验收人还须独立于执行人。</p>
      </template>
      <p v-if="error" role="alert">{{ error }} 输入已保留；核对资料和最新版本后重试。</p>
      <AppButton type="submit" variant="primary" :disabled="disabled">{{ busy?'正在保存…':kind==='job'?'保存维护草稿':'保存'+label }}</AppButton>
    </form>
  </section>
</template>
