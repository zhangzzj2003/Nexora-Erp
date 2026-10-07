<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {NCheckbox,NModal} from 'naive-ui'
import type {EquipmentEntity,MaintenanceAction,MaintenanceJobRecord,MaintenanceCommand} from '../../../../../shared/equipment-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import EquipmentEditor from './EquipmentEditor.vue'
import EquipmentEvidence from './EquipmentEvidence.vue'
import {equipmentStatus,maintenanceStatus,maintenanceKind,maintenanceCommand,maintenanceActions,maintenanceEffect,partsStatus} from './equipment-display'
const store=usePiniaAppStore()
const {equipmentOverview:overview,equipmentDetail:detail,equipmentLoading:loading,equipmentError:failure,busy,user,connectionLost,error}=storeToRefs(store)
const mode=ref<EquipmentEntity>('job'),editor=ref(false),query=ref(''),filter=ref<string|null>(null),preparing=ref(false)
const command=ref<{row:MaintenanceJobRecord;action:MaintenanceAction}|null>(null)
const reason=ref(''),evidence=ref(''),solution=ref(''),hours=ref(''),amount=ref('')
const meterHours=ref(''),meterReference=ref(''),meterReason=ref(''),meterCorrection=ref(false)
const purchaseParts=ref<Record<number,string>>({}),purchaseReason=ref(''),purchaseEvidence=ref('')
const disabled=computed(()=>busy.value || loading.value || preparing.value || connectionLost.value)
const purchaseJob=computed(()=>detail.value?.kind==='job' && detail.value.row.parts.length
  && ['approved','in_progress'].includes(detail.value.row.status) && store.can('purchase_request.view')
  && store.can('purchase_request.create')?detail.value.row:null)
const entityLabel={asset:'设备台账',plan:'日历计划',hour_plan:'运行小时计划',job:'维护工单'}
const assetColumns=[{key:'name',title:'设备 / 序列号'},{key:'location',title:'位置'},{key:'status',title:'状态 / 版本'},{key:'actions',title:'操作 / 证据'}]
const planColumns=[{key:'name',title:'计划 / 设备'},{key:'schedule',title:'到期 / 间隔'},{key:'status',title:'状态 / 工单'},{key:'actions',title:'操作 / 证据'}]
const jobColumns=[{key:'name',title:'依据 / 设备'},{key:'executor',title:'方式 / 执行人'},{key:'status',title:'阶段 / 耗材'},{key:'actions',title:'操作 / 证据'}]
const equipmentName=(id:number)=>{const row=overview.value?.equipment.find(row=>row.id===id);return row?`${row.code} · ${row.name}`:`设备 #${id}`}
const match=(values:unknown[])=>values.join(' ').toLowerCase().includes(query.value.trim().toLowerCase())
const assets=computed(()=>(overview.value?.equipment??[]).filter(row=>(!filter.value || row.status===filter.value) && match([row.code,row.name,row.serial_number,row.location])))
const plans=computed(()=>(overview.value?.plans??[]).filter(row=>(!filter.value || (filter.value==='due'?row.due:!row.enabled)) && match([row.reference,row.title,equipmentName(row.equipment_id)])))
const hourPlans=computed(()=>(overview.value?.hour_plans??[]).filter(row=>(!filter.value || (filter.value==='due'?row.due:!row.enabled))
  && match([row.reference,row.title,equipmentName(row.equipment_id),row.next_due_hours])))
const jobs=computed(()=>(overview.value?.jobs??[]).filter(row=>(!filter.value || row.status===filter.value) && match([documentSearch(row),row.reference,row.equipment_snapshot.code,row.equipment_snapshot.name,row.assigned_to_name,maintenanceStatus[row.status]])))
const filters=computed(()=>[{label:'全部状态',value:null},...(mode.value==='job'?Object.entries(maintenanceStatus).map(([value,label])=>({value,label}))
  :mode.value==='asset'?Object.entries(equipmentStatus).map(([value,label])=>({value,label})):[{label:'已到期',value:'due'},{label:'已停用',value:'disabled'}])])
const actions=(row:MaintenanceJobRecord)=>maintenanceActions(row,user.value?.permissions??[])
const empty=computed(()=>connectionLost.value?'连接恢复后重新读取维护资料。':failure.value?'读取失败，请刷新重试。':query.value || filter.value?'没有匹配的记录，请调整筛选。':mode.value==='asset'?'尚无设备，请由有维护权限的人员建立设备档案。':mode.value==='plan'?'尚无日历计划。':mode.value==='hour_plan'?'尚无运行小时计划，先在设备详情登记表计基线。':'尚无维护工单，可从设备台账或到期计划建立。')
function clearMeter():void{meterHours.value='';meterReference.value='';meterReason.value='';meterCorrection.value=false}
function selectMode(kind:EquipmentEntity):void{if(busy.value || preparing.value)return;mode.value=kind;editor.value=false;query.value='';filter.value=null;clearMeter();store.clearEquipmentDetail()}
function start(kind:EquipmentEntity,id=0,planId:number|null=null,hourPlanId:number|null=null):void{if(!disabled.value && store.startEquipmentRecord(kind,id,planId,hourPlanId)){mode.value=kind;editor.value=true;query.value='';filter.value=null;clearMeter()}}
async function inspect(kind:EquipmentEntity,id:number,edit=false):Promise<void>{
  if(disabled.value)return;preparing.value=true;clearMeter()
  try{if(edit){if(await store.editEquipmentRecord(kind,id))editor.value=true}else await store.loadEquipmentDetail(kind,id)}finally{preparing.value=false}
}
async function prepare(id:number,action:MaintenanceAction):Promise<void>{
  if(disabled.value)return;preparing.value=true;command.value=null;reason.value='';evidence.value='';error.value=''
  try{if(await store.loadEquipmentDetail('job',id) && detail.value?.kind==='job' && actions(detail.value.row).includes(action)){
    command.value={row:detail.value.row,action};solution.value=detail.value.row.solution;hours.value='';amount.value=''
  }}finally{preparing.value=false}
}
async function execute():Promise<void>{
  if(!command.value || disabled.value)return
  const {row,action}=command.value
  const common={id:row.id,version:row.version,reason:reason.value,evidence:evidence.value}
  const payload:MaintenanceCommand=action==='report'?{...common,action,solution:solution.value,labor_hours:hours.value,service_amount:amount.value}:{...common,action}
  if(await store.changeMaintenanceJob(payload))command.value=null
}
async function recordMeter():Promise<void>{
  if(detail.value?.kind!=='asset' || disabled.value)return
  const asset=detail.value.row
  const saved=await store.recordEquipmentMeter({equipment_id:asset.id,hours:meterHours.value,
    reference:meterReference.value,reason:meterReason.value,
    previous_reading_id:asset.meter_reading?.id??null,correction:meterCorrection.value})
  if(saved)clearMeter()
}
async function createPurchaseRequest():Promise<void>{
  const job=purchaseJob.value
  if(!job || disabled.value)return
  const parts=job.parts.filter(part=>purchaseParts.value[part.material_id]?.trim())
    .map(part=>({material_id:part.material_id,quantity:purchaseParts.value[part.material_id].trim()}))
  if(!parts.length)return
  const saved=await store.createMaintenancePurchaseRequest({id:job.id,version:job.version,
    reason:purchaseReason.value,evidence:purchaseEvidence.value,parts})
  if(saved){purchaseParts.value={};purchaseReason.value='';purchaseEvidence.value=''}
}
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{
  command.value=null;editor.value=false;reason.value='';evidence.value='';solution.value='';hours.value='';amount.value='';query.value='';filter.value=null;purchaseParts.value={};purchaseReason.value='';purchaseEvidence.value='';clearMeter()
  if(!connectionLost.value && store.can('equipment.view'))void store.loadEquipment()
})
watch(connectionLost,()=>{command.value=null;if(!connectionLost.value && store.can('equipment.view'))void store.loadEquipment()})
onMounted(()=>{void store.loadEquipment()});onUnmounted(()=>store.clearEquipmentDetail())
</script>
<template>
  <section class="stack equipment-workspace">
    <p v-if="!store.can('equipment.view')" role="alert">当前账号没有设备维护查看权限，请联系管理员核对授权。</p>
    <template v-else>
      <div class="equipment-toolbar"><AppButton v-for="kind in (['job','asset','plan','hour_plan'] as const)" :key="kind" :variant="mode===kind?'primary':'secondary'" :disabled="busy || preparing" @click="selectMode(kind)">{{ entityLabel[kind] }}</AppButton><AppButton :disabled="disabled" @click="store.loadEquipment()">{{ loading?'正在读取…':'刷新维护资料' }}</AppButton></div>
      <p v-if="connectionLost" role="alert">服务端连接中断，旧证据与动作已失效。未保存正文和修订版本保留；恢复后须核对最新记录。</p>
      <p v-if="failure" role="alert">{{ failure }} 请刷新维护资料后重试。</p>
      <EquipmentEditor v-if="editor" :kind="mode" @saved="editor=false" @close="editor=false" />
      <template v-else>
        <WorkspaceTable v-if="mode==='asset'" title="设备台账" :show-title="false" :columns="assetColumns" :data="assets" :min-table-width="1000" :loading="loading">
          <template #filters><label>搜索设备<AppInput v-model="query" placeholder="设备编号、名称、序列号或位置" /></label><label>设备状态<WorkspaceSelect v-model="filter" :options="filters" /></label></template>
          <template #actions><AppButton v-if="store.can('equipment.manage')" :disabled="disabled" @click="start('asset')">新建设备</AppButton></template>
          <template #cell-name="{row}"><strong>{{ row.code }} · {{ row.name }}</strong><span class="equipment-secondary">{{ row.serial_number || '无序列号' }}</span></template>
          <template #cell-location="{row}">{{ row.location || '未登记' }}</template>
          <template #cell-status="{row}">{{ equipmentStatus[row.status as keyof typeof equipmentStatus] }} · v{{ row.version }}<span class="equipment-secondary">{{ row.meter_reading?`表计 ${row.meter_reading.hours} 小时`:'未登记表计' }}</span><span v-if="row.running_job_ids.length" class="equipment-secondary">工单 {{ row.running_job_ids.map((id:number)=>'#'+id).join('、') }} 执行中或待验收</span></template>
          <template #cell-actions="{row}"><div class="equipment-toolbar"><AppButton size="small" :disabled="disabled" @click="inspect('asset',row.id)">详情与历史</AppButton><AppButton v-if="store.can('equipment.manage')" size="small" :disabled="disabled" @click="inspect('asset',row.id,true)">修订设备</AppButton><AppButton v-if="store.can('equipment.create') && row.status==='active'" size="small" :disabled="disabled" @click="start('job',row.id)">故障维修</AppButton><AppButton v-if="store.can('equipment.manage') && row.status==='active'" size="small" :disabled="disabled" @click="start('plan',row.id)">建立日历计划</AppButton><AppButton v-if="store.can('equipment.manage') && row.status==='active' && row.meter_reading" size="small" :disabled="disabled" @click="start('hour_plan',row.id)">建立小时计划</AppButton></div></template>
          <template #empty>{{ empty }}</template>
        </WorkspaceTable>
        <WorkspaceTable v-else-if="mode==='plan'" title="周期计划" :show-title="false" :columns="planColumns" :data="plans" :min-table-width="1000" :loading="loading">
          <template #filters><label>搜索周期计划<AppInput v-model="query" placeholder="计划依据、内容或设备" /></label><label>计划状态<WorkspaceSelect v-model="filter" :options="filters" /></label></template>
          <template #actions><AppButton v-if="store.can('equipment.manage')" :disabled="disabled" @click="start('plan')">新建周期计划</AppButton></template>
          <template #cell-name="{row}"><strong>{{ row.reference }} · {{ row.title }}</strong><span class="equipment-secondary">{{ equipmentName(row.equipment_id) }}</span></template>
          <template #cell-schedule="{row}">{{ row.next_due }}（UTC 日期）<span class="equipment-secondary">间隔 {{ row.interval_days }} 天 · v{{ row.version }}</span></template>
          <template #cell-status="{row}">{{ !row.enabled?'已停用':row.due?'已到期':'未到期' }}<span v-if="row.open_job_ids.length" class="equipment-secondary">未结束工单 {{ row.open_job_ids.map((id:number)=>'#'+id).join('、') }}</span></template>
          <template #cell-actions="{row}"><div class="equipment-toolbar"><AppButton size="small" :disabled="disabled" @click="inspect('plan',row.id)">详情与历史</AppButton><AppButton v-if="store.can('equipment.manage') && !row.open_job_ids.length" size="small" :disabled="disabled" @click="inspect('plan',row.id,true)">修订计划</AppButton><AppButton v-if="store.can('equipment.create') && row.due && !row.open_job_ids.length" size="small" :disabled="disabled" @click="start('job',row.equipment_id,row.id)">建立周期保养</AppButton></div></template>
          <template #empty>{{ empty }}</template>
        </WorkspaceTable>
        <WorkspaceTable v-else-if="mode==='hour_plan'" title="运行小时计划" :show-title="false" :columns="planColumns" :data="hourPlans" :min-table-width="1000" :loading="loading">
          <template #filters><label>搜索运行小时计划<AppInput v-model="query" placeholder="依据、内容、设备或阈值" /></label><label>计划状态<WorkspaceSelect v-model="filter" :options="filters" /></label></template>
          <template #actions><AppButton v-if="store.can('equipment.manage')" :disabled="disabled" @click="start('hour_plan')">新建运行小时计划</AppButton></template>
          <template #cell-name="{row}"><strong>{{ row.reference }} · {{ row.title }}</strong><span class="equipment-secondary">{{ equipmentName(row.equipment_id) }}</span></template>
          <template #cell-schedule="{row}">阈值 {{ row.next_due_hours }} 小时<span class="equipment-secondary">当前 {{ row.current_hours??'未登记' }} 小时 · 间隔 {{ row.interval_hours }} 小时 · v{{ row.version }}</span></template>
          <template #cell-status="{row}">{{ !row.enabled?'已停用':row.due?'已到期':'未到期' }}<span v-if="row.open_job_ids.length" class="equipment-secondary">未结束工单 {{ row.open_job_ids.map((id:number)=>'#'+id).join('、') }}</span></template>
          <template #cell-actions="{row}"><div class="equipment-toolbar"><AppButton size="small" :disabled="disabled" @click="inspect('hour_plan',row.id)">详情与历史</AppButton><AppButton v-if="store.can('equipment.manage') && !row.open_job_ids.length" size="small" :disabled="disabled" @click="inspect('hour_plan',row.id,true)">修订计划</AppButton><AppButton v-if="store.can('equipment.create') && row.due && !row.open_job_ids.length" size="small" :disabled="disabled" @click="start('job',row.equipment_id,null,row.id)">建立小时保养</AppButton></div></template>
          <template #empty>{{ empty }}</template>
        </WorkspaceTable>
        <WorkspaceTable v-else title="维护工单" :show-title="false" :columns="jobColumns" :data="jobs" :min-table-width="1150" :loading="loading">
          <template #filters><label>搜索维护工单<AppInput v-model="query" placeholder="依据编号、设备或执行人" /></label><label>维护阶段<WorkspaceSelect v-model="filter" :options="filters" /></label></template>
          <template #actions><AppButton v-if="store.can('equipment.create')" :disabled="disabled" @click="start('job')">新建维护工单</AppButton></template>
          <template #cell-name="{row}"><strong>{{ documentLabel(row) }}</strong><span class="equipment-secondary">{{ row.reference }} · {{ row.equipment_snapshot.code }} · {{ row.equipment_snapshot.name }}</span></template>
          <template #cell-executor="{row}">{{ maintenanceKind[row.kind as keyof typeof maintenanceKind] }} · {{ row.assigned_to_name }}<span v-if="row.plan_due_date" class="equipment-secondary">本次到期 {{ row.plan_due_date }}</span><span v-if="row.plan_due_hours" class="equipment-secondary">本次阈值 {{ row.plan_due_hours }} 小时</span></template>
          <template #cell-status="{row}">{{ maintenanceStatus[row.status as keyof typeof maintenanceStatus] }} · v{{ row.version }}<span v-if="row.parts_outbound_id" class="equipment-secondary">出库 {{ relatedDocumentLabel(row, 'parts_outbound') }} · {{ partsStatus[row.parts_status as keyof typeof partsStatus] }}</span></template>
          <template #cell-actions="{row}"><div class="equipment-toolbar"><AppButton size="small" :disabled="disabled" @click="inspect('job',row.id)">详情与证据</AppButton><AppButton v-if="row.can_edit && store.can('equipment.create')" size="small" :disabled="disabled" @click="inspect('job',row.id,true)">修订工单</AppButton><AppButton v-for="action in actions(row)" :key="action" size="small" :disabled="disabled" @click="prepare(row.id,action)">{{ maintenanceCommand[action] }}</AppButton></div></template>
          <template #empty>{{ empty }}</template>
        </WorkspaceTable>
        <p v-if="overview" class="equipment-secondary">读取时间：{{ store.localTime(overview.as_of) }}。停机时长为此时的登记区间，不等于现场自动采集或生产工时。</p>
        <EquipmentEvidence v-if="detail" :detail="detail" />
        <form v-if="purchaseJob" class="equipment-operation" @submit.prevent="createPurchaseRequest">
          <h3>从维护工单申请备件采购</h3>
          <p>按已批准的耗材数量填写本次采购量。创建后进入采购申请草稿，仍须提交、审核、转采购订单和收货入库；取消的申请不占用数量。</p>
          <div v-for="part in purchaseJob.parts" :key="part.material_id" class="equipment-facts">
            <label>{{ overview?.materials.find(item=>item.id===part.material_id)?.name || '物料 #'+part.material_id }} · 计划 {{ part.quantity }}
              <AppInput v-model="purchaseParts[part.material_id]" type="number" min="0.001" max="1000000" step="0.001" placeholder="留空表示本次不采购" :disabled="disabled" />
            </label>
          </div>
          <label>采购原因<AppInput v-model.trim="purchaseReason" maxlength="200" required :disabled="disabled" /></label>
          <label>采购依据<AppInput v-model.trim="purchaseEvidence" maxlength="600" required :disabled="disabled" /></label>
          <p v-if="error" role="alert">{{ error }} 请复核工单版本及剩余可申请数量。</p>
          <AppButton type="submit" variant="primary" :disabled="disabled || !purchaseReason.trim() || !purchaseEvidence.trim() || !Object.values(purchaseParts).some(value=>value?.trim())">创建采购申请草稿</AppButton>
        </form>
        <form v-if="detail?.kind==='asset' && detail.row.status==='active' && store.can('equipment.meter')" class="equipment-operation" @submit.prevent="recordMeter">
          <h3>登记设备运行小时</h3>
          <p>基于设备 {{ documentLabel(detail.row) }} 当前读数 {{ detail.row.meter_reading?.hours??'未登记' }} 小时。普通登记不能倒退；错误读数由有设备资料权限的账号追加更正，原记录保留。</p>
          <div class="equipment-facts"><label>表计小时<AppInput v-model="meterHours" type="number" min="0" max="1000000000" step="0.01" required :disabled="disabled" /></label><label>读数依据编号<AppInput v-model.trim="meterReference" maxlength="100" required :disabled="disabled" /></label></div>
          <label>登记或更正原因<AppInput v-model.trim="meterReason" maxlength="200" required :disabled="disabled" /></label>
          <NCheckbox v-if="store.can('equipment.manage')" v-model:checked="meterCorrection" :disabled="disabled">更正此前错误读数（允许降低当前小时）</NCheckbox>
          <p v-if="error" role="alert">{{ error }} 输入已保留，请核对最新读数和依据后重试。</p>
          <AppButton type="submit" variant="primary" :disabled="disabled">登记读数</AppButton>
        </form>
      </template>
      <NModal :show="!!command" preset="card" :title="command?maintenanceCommand[command.action]:''" :style="{width:'min(760px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value)command=null}">
        <form v-if="command" class="equipment-operation" @submit.prevent="execute">
          <EquipmentEvidence :detail="{kind:'job',row:command.row}" compact />
          <p>{{ maintenanceEffect(command.action) }}</p>
          <template v-if="command.action==='report'">
            <label>本次处理结果<AppInput v-model.trim="solution" maxlength="600" required :disabled="busy" /></label>
            <div class="equipment-facts"><label>实际工时（小时）<AppInput v-model="hours" type="number" min="0" max="100000" step="0.01" required :disabled="busy" /></label><label>声明外委费用（人民币元）<AppInput v-model="amount" type="number" min="0" max="1000000000" step="0.01" required :disabled="busy" /></label></div>
          </template>
          <label>操作原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
          <label>操作或验收依据<AppInput v-model.trim="evidence" maxlength="600" required :disabled="busy" /></label>
          <p v-if="error" role="alert">{{ error }} 原因与依据保留；关闭后读取最新证据，复核状态与版本后重试。</p>
          <AppButton type="submit" variant="primary" :disabled="disabled || !reason.trim() || !evidence.trim()">{{ busy?'正在处理…':maintenanceCommand[command.action] }}</AppButton>
        </form>
      </NModal>
    </template>
  </section>
</template>
<style>
.equipment-workspace,.equipment-evidence{--equipment-secondary:#50667d;overflow-wrap:anywhere}
:root[data-theme='dark'] .equipment-workspace,:root[data-theme='dark'] .equipment-evidence{--equipment-secondary:#9aadc5}
.equipment-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.equipment-secondary{display:block;margin-top:4px;font-size:12px;color:var(--equipment-secondary);overflow-wrap:anywhere}
.equipment-editor form,.equipment-operation{display:grid;gap:18px}
.equipment-wide{grid-column:1/-1}
.equipment-part{display:grid;grid-template-columns:minmax(240px,2fr) minmax(150px,1fr) auto;gap:12px;align-items:end;margin-top:12px}
.equipment-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}
.equipment-facts dt{color:var(--equipment-secondary);font-size:12px;margin-bottom:6px}
.equipment-facts dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
.equipment-facts>*,.equipment-editor .form-grid>*{min-width:0}
@media(max-width:1000px){.equipment-editor .form-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.equipment-part{grid-template-columns:minmax(0,1fr) minmax(120px,1fr)}.equipment-part button{justify-self:start}}
@media(max-width:600px){.equipment-facts,.equipment-editor .form-grid,.equipment-part{grid-template-columns:minmax(0,1fr)}}
</style>
