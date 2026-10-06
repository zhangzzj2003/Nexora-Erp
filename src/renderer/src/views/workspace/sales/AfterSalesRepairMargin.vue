<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {storeToRefs} from 'pinia'
import {NCollapse} from 'naive-ui'
import type {AfterSalesEvidence,AfterSalesRepairMargin} from '../../../../../shared/after-sales-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'

const props=defineProps<{row:AfterSalesEvidence}>()
const store=usePiniaAppStore()
const {busy,connectionLost,user}=storeToRefs(store)
const summary=ref<AfterSalesRepairMargin|null>(null)
const loading=ref(false),error=ref('')
const disabled=computed(()=>busy.value||connectionLost.value||loading.value)
const costSourceLabel=(value:string):string=>({moving_average:'移动平均',manual:'人工核价',
  linked_movement:'原单沿用',purchase_order:'采购单价',production_settlement:'完工结算',
  unpriced:'待核价'} as Record<string,string>)[value]??value
let generation=0
async function refresh():Promise<void>{
  const ticket=++generation;summary.value=null;error.value='';loading.value=false
  if(connectionLost.value||!store.can('after_sales.cost')||!store.can('after_sales.view'))return
  loading.value=true
  try{
    const result=await store.loadAfterSalesRepairMargin(props.row.id)
    if(ticket===generation&&result.case_version===props.row.version)summary.value=result
  }catch(caught){if(ticket===generation)error.value=caught instanceof Error?caught.message:String(caught)}
  finally{if(ticket===generation)loading.value=false}
}
watch(()=>[props.row.id,props.row.version,user.value?.id,user.value?.permissions.join('|'),connectionLost.value],
  ()=>{void refresh()},{immediate:true})
</script>
<template>
  <section class="repair-margin" aria-label="维修项目直接毛利">
    <div class="margin-heading"><h3>维修项目直接毛利</h3><AppButton :disabled="disabled" @click="refresh">刷新成本与毛利</AppButton></div>
    <p>按已结案服务费减有效工时内部核价与公司耗材的库存计价计算；不包含税费、间接费用及工资凭证。</p>
    <p v-if="error" role="alert">{{ error }} 请刷新售后证据后重新读取。</p>
    <p v-if="loading">正在核对维修收入与成本来源…</p>
    <template v-if="summary">
      <p>已确认服务费 {{ summary.revenue }} 元；耗材成本 {{ summary.material_cost??'待核价' }} 元；工时成本 {{ summary.labor_cost??'待核价' }} 元。</p>
      <p v-if="summary.complete"><strong>直接成本 {{ summary.total_direct_cost }} 元，直接毛利 {{ summary.direct_margin }} 元。</strong></p>
      <p v-else role="status">暂不计算直接毛利：{{ !summary.finalized?'维修尚未结案；':'' }}{{ summary.parts_pending?'耗材出库尚未确认；':'' }}{{ summary.missing_labor_ids.length?`工时 #${summary.missing_labor_ids.join('、')} 尚未核价；`:'' }}{{ summary.unpriced_movement_ids.length?`库存流水 #${summary.unpriced_movement_ids.join('、')} 缺少成本；`:'' }}</p>
      <NCollapse v-if="summary.movements.length"><AppCollapseItem name="material" title="查看耗材成本流水">
        <ul><li v-for="item in summary.movements" :key="item.id">
          流水 #{{ item.id }} · 出库明细 #{{ item.source_line_id }} · 物料 #{{ item.material_id }} · {{ item.source_type==='other_outbound'?'耗用':'冲销' }} {{ item.quantity }} · 成本 {{ item.cost??'待核价' }} 元 · 计价来源 {{ costSourceLabel(item.cost_source) }}{{ item.cost_input_id?`（核价 #${item.cost_input_id}）`:'' }}
        </li></ul>
      </AppCollapseItem></NCollapse>
    </template>
  </section>
</template>
<style scoped>
.repair-margin{display:grid;gap:10px}.repair-margin p,.repair-margin h3{margin:0}
.margin-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.repair-margin li{margin:8px 0}
</style>
