<script setup lang="ts">
import {computed} from 'vue'
import {NCollapse} from 'naive-ui'
import type {EquipmentDetail} from '../../../../../shared/equipment-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import EquipmentAttachments from './EquipmentAttachments.vue'
import {equipmentStatus,maintenanceStatus,maintenanceKind,maintenanceCommand,equipmentChanges,downtimeLabel,partsStatus} from './equipment-display'
const props=defineProps<{detail:EquipmentDetail;compact?:boolean}>(),store=usePiniaAppStore()
const title=computed(()=>props.detail.kind==='asset'?props.detail.row.code:props.detail.row.reference)
const asset=computed(()=>props.detail.kind==='asset'?props.detail.row:null)
const plan=computed(()=>props.detail.kind==='plan'?props.detail.row:null)
const hourPlan=computed(()=>props.detail.kind==='hour_plan'?props.detail.row:null)
const job=computed(()=>props.detail.kind==='job'?props.detail.row:null)
const material=(id:number)=>store.equipmentOverview?.materials.find(row=>row.id===id)
const orderStatus:Record<string,string>={draft:'草稿',released:'已下达',in_progress:'生产中',completed:'已完工',cancelled:'已取消'}
function changeLabel(action:string):string{return maintenanceCommand[action as keyof typeof maintenanceCommand]??({create:'建立记录',edit:'修订记录',advance:'推进计划',restore_due:'恢复到期阈值'}[action]??action)}
</script>
<template>
  <section class="equipment-evidence" :aria-label="`${title} 的维护证据`">
    <h3>{{ title }} · v{{ detail.row.version }}</h3>
    <dl v-if="asset" class="equipment-facts">
      <div><dt>设备</dt><dd>{{ asset.name }} · {{ equipmentStatus[asset.status] }}</dd></div>
      <div><dt>序列号 / 位置</dt><dd>{{ asset.serial_number || '无序列号' }} · {{ asset.location || '未登记位置' }}</dd></div>
      <div><dt>未结束维护</dt><dd>{{ asset.running_job_ids.length?asset.running_job_ids.map(id=>'#'+id).join('、'):'无执行中或待验收工单' }}</dd></div>
      <div><dt>最新运行小时</dt><dd>{{ asset.meter_reading?`${asset.meter_reading.hours} 小时 · ${asset.meter_reading.reference}`:'尚无表计基线' }}</dd></div>
    </dl>
    <dl v-if="hourPlan" class="equipment-facts">
      <div><dt>设备 / 内容</dt><dd>设备 #{{ hourPlan.equipment_id }} · {{ hourPlan.title }}</dd></div>
      <div><dt>表计安排</dt><dd>{{ hourPlan.enabled?'启用':'停用' }} · 间隔 {{ hourPlan.interval_hours }} 小时 · 阈值 {{ hourPlan.next_due_hours }} 小时</dd></div>
      <div><dt>最新读数</dt><dd>{{ hourPlan.current_hours===null?'未登记':hourPlan.current_hours+' 小时' }} · {{ hourPlan.due?'已到期':'未到期' }}</dd></div>
      <div><dt>未结束工单</dt><dd>{{ hourPlan.open_job_ids.length?hourPlan.open_job_ids.map(id=>'#'+id).join('、'):'无' }}</dd></div>
    </dl>
    <dl v-if="plan" class="equipment-facts">
      <div><dt>设备 / 内容</dt><dd>设备 #{{ plan.equipment_id }} · {{ plan.title }}</dd></div>
      <div><dt>日历安排</dt><dd>{{ plan.enabled?'启用':'停用' }} · 间隔 {{ plan.interval_days }} 天 · 到期 {{ plan.next_due }}（UTC 日期）</dd></div>
      <div><dt>未结束工单</dt><dd>{{ plan.open_job_ids.length?plan.open_job_ids.map(id=>'#'+id).join('、'):'无' }}</dd></div>
    </dl>
    <template v-if="job">
      <dl class="equipment-facts">
        <div><dt>维护阶段</dt><dd>{{ maintenanceStatus[job.status] }} · {{ maintenanceKind[job.kind] }}</dd></div>
        <div><dt>设备保存快照</dt><dd>{{ job.equipment_snapshot.code }} · {{ job.equipment_snapshot.name }} · {{ job.equipment_snapshot.location || '未登记位置' }}</dd></div>
        <div><dt>执行 / 编制</dt><dd>{{ job.assigned_to_name }} / {{ job.created_by_name }}</dd></div>
        <div v-if="job.plan_id"><dt>本次计划快照</dt><dd>计划 #{{ job.plan_id }} · v{{ job.plan_version }} · 到期 {{ job.plan_due_date }}（UTC 日期）</dd></div>
        <div v-if="job.hour_plan_id"><dt>本次运行小时快照</dt><dd>计划 #{{ job.hour_plan_id }} · v{{ job.plan_version }} · 阈值 {{ job.plan_due_hours }} 小时 · 建单读数 #{{ job.plan_meter_reading_id }}</dd></div>
        <div><dt>维护要求</dt><dd>{{ job.request_note }}</dd></div>
        <div v-if="job.work_order_linked"><dt>生产影响关联</dt><dd v-if="store.can('production.view')">生产工单 #{{ job.work_order_id }} · 当前 {{ orderStatus[job.work_order_current_status??'']??'未读取' }}<br>关联仅说明影响，不自动约束排产或改变工单。</dd><dd v-else>已关联生产工单；详细内容需生产查看权限。</dd></div>
        <div><dt>处理结果</dt><dd>{{ job.solution || '尚未报工' }}</dd></div>
        <div><dt>实际工时 / 声明外委费用</dt><dd>{{ job.labor_hours===null?'未报工':job.labor_hours+' 小时' }} / {{ job.service_amount===null?'未声明':job.service_amount+' 元（人民币）' }}<br>声明费用不自动生成应付或总账。</dd></div>
        <div v-if="job.downtime"><dt>登记停机</dt><dd>{{ store.localTime(job.downtime.started_at) }} 至 {{ job.downtime.ended_at?store.localTime(job.downtime.ended_at):'尚未结束' }}<br>{{ downtimeLabel(job.downtime) }}<template v-if="job.downtime.close_reason"><br>结束依据：{{ job.downtime.close_reason }}</template></dd></div>
        <div v-if="job.parts_outbound_id"><dt>耗材出库</dt><dd>#{{ job.parts_outbound_id }} · {{ job.parts_status?partsStatus[job.parts_status]:'未读取' }}<br><RouterLink v-if="store.can('other_outbound.view')" to="/workspace/warehouse-outbounds">前往仓库确认或更正</RouterLink></dd></div>
      </dl>
      <ul v-if="job.parts.length"><li v-for="part in job.parts" :key="part.material_id">物料 #{{ part.material_id }} · {{ material(part.material_id)?.name || '按原编号核对' }} · {{ part.quantity }} {{ material(part.material_id)?.unit }}</li></ul>
      <p v-else>未登记耗材，不产生维护出库。</p>
      <p v-if="job.plan_roll.reversal_effect==='restored_due'">验收更正已恢复原计划到期阈值；停机和实际领用历史保留。</p>
      <p v-else-if="job.plan_roll.reversal_effect==='retained_newer_schedule'">计划已被后续修订或工单使用，保留较新安排。请另行复核周期计划。</p>
    </template>
    <template v-if="asset && !compact"><h4>运行小时读数历史</h4><p v-if="!asset.meter_readings.length">尚未登记表计读数。</p><ul v-else><li v-for="reading in asset.meter_readings" :key="reading.id">#{{ reading.id }} · {{ reading.hours }} 小时 · {{ reading.correction?'更正':'常规登记' }} · {{ reading.reference }} · {{ reading.reason }} · {{ reading.recorded_by_name }} · {{ store.localTime(reading.recorded_at) }}</li></ul><h4>停机区间</h4><p v-if="!asset.downtimes.length">尚无已开始维护登记。</p><ul v-else><li v-for="entry in asset.downtimes" :key="entry.id">工单 #{{ entry.job_id }} · {{ store.localTime(entry.started_at) }} 至 {{ entry.ended_at?store.localTime(entry.ended_at):'尚未结束' }} · {{ downtimeLabel(entry) }} · {{ entry.close_reason }}</li></ul></template>
    <template v-if="!compact">
      <EquipmentAttachments v-if="asset || job" :kind="asset?'asset':'job'" :record-id="detail.row.id" :record-version="detail.row.version" />
      <h3>操作与更正历史</h3>
      <NCollapse><AppCollapseItem v-for="change in detail.row.changes" :key="change.id" :name="change.id" :title="`${changeLabel(change.action)} · ${change.changed_by_name} · ${store.localTime(change.created_at)}`">
        <p>原因：{{ change.reason }}</p><p v-if="change.evidence">依据：{{ change.evidence }}</p>
        <dl class="equipment-facts"><div v-for="entry in equipmentChanges(change)" :key="entry.name"><dt>{{ entry.name }}</dt><dd>之前：{{ entry.before }}<br>之后：{{ entry.after }}</dd></div></dl>
      </AppCollapseItem></NCollapse>
    </template>
  </section>
</template>
