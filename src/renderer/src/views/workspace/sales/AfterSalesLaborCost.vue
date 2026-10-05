<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {NCollapse,NModal} from 'naive-ui'
import type {AfterSalesEvidence,AfterSalesLaborCostSummary} from '../../../../../shared/after-sales-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'

const props=defineProps<{row:AfterSalesEvidence}>()
const store=usePiniaAppStore()
const {busy,connectionLost,user,error:writeError}=storeToRefs(store)
const summary=ref<AfterSalesLaborCostSummary|null>(null)
const error=ref(''),loading=ref(false)
const command=ref<{entryId:number;void:boolean}|null>(null)
const hourlyRate=ref(''),reason=ref(''),evidence=ref('')
const disabled=computed(()=>busy.value||connectionLost.value||loading.value)
let generation=0
async function refresh():Promise<void>{
  const ticket=++generation;summary.value=null;error.value='';loading.value=false
  if(connectionLost.value||!store.can('after_sales.cost')||!store.can('after_sales.view'))return
  loading.value=true
  try{
    const data=await store.loadAfterSalesLaborCost(props.row.id)
    if(ticket===generation&&data.case_version===props.row.version)summary.value=data
  }catch(caught){if(ticket===generation)error.value=caught instanceof Error?caught.message:String(caught)}
  finally{if(ticket===generation)loading.value=false}
}
watch(()=>[props.row.id,props.row.version,user.value?.id,user.value?.permissions.join('|'),connectionLost.value],()=>{
  command.value=null;void refresh()
},{immediate:true})
function open(entryId:number,clear:boolean):void{
  if(disabled.value||!summary.value||summary.value.case_version!==props.row.version)return
  const entry=summary.value.entries.find(item=>item.labor_id===entryId)
  const labor=props.row.labor.find(item=>item.id===entryId)
  if(!entry||entry.reversed||labor?.created_by===user.value?.id||clear&&entry.latest?.action!=='set')return
  command.value={entryId,void:clear};hourlyRate.value=clear?'':entry.latest?.hourly_rate??''
  reason.value='';evidence.value='';error.value=''
}
async function save():Promise<void>{
  if(!command.value||disabled.value||!reason.value.trim()||!evidence.value.trim())return
  if(!command.value.void&&!hourlyRate.value.trim())return
  try{
    const result=await store.valueAfterSalesLaborCost(props.row,command.value.entryId,
      command.value.void?null:hourlyRate.value.trim(),reason.value,evidence.value)
    if(result){summary.value=result;command.value=null;error.value=''}
    else if(writeError.value)error.value=writeError.value
  }catch(caught){error.value=caught instanceof Error?caught.message:String(caught)}
}
</script>
<template>
  <section class="labor-cost" aria-label="维修工时内部成本">
    <h3>维修工时内部成本</h3>
    <p>按每条有效工时核定人民币内部标准小时成本；该核价不生成工资、应付、维修收费或总账凭证。</p>
    <p v-if="error" role="alert">{{ error }} 请重新读取并核对版本。</p>
    <p v-if="loading">正在读取内部成本…</p>
    <template v-if="summary">
      <p>当前有效工时成本 {{ summary.total_amount }} 元；未核价 {{ summary.missing_labor_ids.length }} 条。</p>
      <ul>
        <li v-for="entry in summary.entries" :key="entry.labor_id">
          工时 #{{ entry.labor_id }} · {{ entry.hours }} 小时 ·
          {{ entry.reversed?'已更正，不计入合计':entry.latest?.action==='set'?`${entry.latest.hourly_rate} 元/小时，计 ${entry.latest.amount} 元`:'待核价' }}
          <span v-if="!entry.reversed&&row.labor.find(item=>item.id===entry.labor_id)?.created_by!==user?.id">
            <AppButton :disabled="disabled" @click="open(entry.labor_id,false)">{{ entry.latest?.action==='set'?'更正核价':'核定成本' }}</AppButton>
            <AppButton v-if="entry.latest?.action==='set'" :disabled="disabled" @click="open(entry.labor_id,true)">撤销核价</AppButton>
          </span>
        </li>
      </ul>
      <NCollapse v-if="summary.history.length"><AppCollapseItem name="history" title="查看全部核价与更正历史">
        <ul><li v-for="item in summary.history" :key="item.id">
          #{{ item.id }} · 工时 #{{ item.labor_id }} · {{ item.action==='set'?`${item.hourly_rate} 元/小时，${item.amount} 元`:'撤销核价' }}
          · {{ item.created_by_name }} · {{ store.localTime(item.created_at) }}<br>原因：{{ item.reason }}；依据：{{ item.evidence }}
        </li></ul>
      </AppCollapseItem></NCollapse>
    </template>
    <NModal :show="!!command" preset="card" :title="command?.void?'撤销内部核价':'核定内部工时成本'" style="width:min(650px,calc(100vw - 48px))" :mask-closable="!busy" :closable="!busy" @update:show="value=>{if(!value&&!busy)command=null}">
      <form v-if="command" class="cost-form" @submit.prevent="save">
        <p>工时 #{{ command.entryId }} · 售后版本 v{{ row.version }}。更正会追加新记录，原核价与依据继续保留。</p>
        <label v-if="!command.void">内部标准小时成本（元）<AppInput v-model.trim="hourlyRate" type="number" min="0.01" max="100000" step="0.01" required :disabled="busy" /></label>
        <label>核价或更正原因<AppInput v-model.trim="reason" maxlength="200" required :disabled="busy" /></label>
        <label>内部依据<AppInput v-model.trim="evidence" maxlength="400" required :disabled="busy" /></label>
        <p v-if="error" role="alert">{{ error }}</p>
        <div class="cost-actions"><AppButton type="submit" variant="primary" :disabled="disabled||!reason.trim()||!evidence.trim()||(!command.void&&!hourlyRate.trim())">保存核价</AppButton><AppButton :disabled="busy" @click="command=null">取消</AppButton></div>
      </form>
    </NModal>
  </section>
</template>
<style scoped>
.labor-cost{display:grid;gap:10px}.labor-cost h3,.labor-cost p{margin:0}.labor-cost li{margin:8px 0}.labor-cost li button{margin-left:8px}
.cost-form{display:grid;gap:18px}.cost-actions{display:flex;flex-wrap:wrap;gap:8px}
</style>
