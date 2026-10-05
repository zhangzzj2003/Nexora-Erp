<script setup lang="ts">
import {NCollapse} from 'naive-ui'
import type {AfterSalesEvidence} from '../../../../../shared/after-sales-api'
import {usePiniaAppStore} from '../../../store/app-store'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import {afterSalesKind,afterSalesStatus,afterSalesChanges,afterSalesCommand,afterSalesResponsibility,repairFeeState} from './after-sales-display'
defineProps<{row:AfterSalesEvidence;compact?:boolean}>()
const store=usePiniaAppStore()
</script>
<template>
  <section class="after-evidence" :aria-label="`售后 ${row.reference} 的证据`">
    <h3>{{ row.reference }} · {{ afterSalesStatus[row.status] }} · v{{ row.version }}</h3>
    <dl class="after-facts">
      <div><dt>客户与原单</dt><dd>{{ row.frozen_source.customer_name }} · 销售订单 #{{ row.frozen_source.sales_order_id }} · 出库 #{{ row.frozen_source.shipment_id }} / 明细 #{{ row.shipment_line_id }}</dd></div>
      <div><dt>物品与本次数量</dt><dd>{{ row.frozen_source.sku }} · {{ row.frozen_source.material_name }} · {{ afterSalesKind[row.kind] }} {{ row.quantity }} {{ row.frozen_source.unit }}</dd></div>
      <div><dt>客户诉求</dt><dd>{{ row.complaint }}</dd></div><div><dt>办理方案</dt><dd>{{ row.solution }}</dd></div>
      <div><dt>客户同意依据</dt><dd>{{ row.customer_acceptance }}</dd></div><div><dt>原出库效力</dt><dd>{{ row.current_source_valid?'当前有效':'当前来源已更正，请核对历史' }}</dd></div>
      <div><dt>保修期限核对</dt><dd v-if="row.warranty_days!==null">出库日 {{ row.frozen_source.posted_at.slice(0,10) }} · {{ row.warranty_days }} 天 · 截止 {{ row.warranty_expires_on }}；申请日 {{ row.warranty_applied_on }} · {{ row.warranty_status==='within_period'?'期限内':row.warranty_status==='expired'?'已过期':'日期待核对' }}</dd><dd v-else>未确认保修条款</dd></div>
      <div><dt>保修依据</dt><dd>{{ row.warranty_basis||'未提供；请人工核对合同' }}</dd></div>
      <div><dt>最新责任核定</dt><dd v-if="row.responsibility">{{ afterSalesResponsibility[row.responsibility.outcome] }} · {{ row.responsibility.assessed_by_name }} · {{ store.localTime(row.responsibility.created_at) }}<br>{{ row.responsibility.basis }}</dd><dd v-else>尚未人工核定</dd></div>
    </dl>
    <p>期限核对不自动认定保修责任；人工责任核定也不自动改变本单收费方案，请核对合同、故障与客户同意依据。</p>
    <ul v-if="!compact&&row.responsibilities.length"><li v-for="item in row.responsibilities" :key="item.id">责任核定 #{{ item.id }} · {{ afterSalesResponsibility[item.outcome] }} · {{ item.assessed_by_name }} · {{ store.localTime(item.created_at) }}<p>原因：{{ item.reason }}；依据：{{ item.basis }}</p></li></ul>
    <template v-if="row.kind==='exchange'">
      <p>{{ row.frozen_source.replacement?.sku }} · {{ row.frozen_source.replacement?.material_name }} · 换货 {{ row.replacement_quantity }} {{ row.frozen_source.replacement?.unit }} · 单价 {{ row.replacement_unit_price }} 元。原退货与换货分别核对，不自动抵销价差。</p>
    </template>
    <template v-if="row.kind==='repair'">
      <p>{{ row.charge_mode==='free'?'明确免费维修':`整单维修服务费 ${row.fee_amount} 元` }}；{{ repairFeeState(row) }}。</p>
      <p>客户物品在管 {{ row.custody_quantity }} {{ row.frozen_source.unit }}，不计入公司可售库存。</p>
      <p>已记录净维修工时 {{ row.labor_hours }} 小时。工时只是实际作业证据，不自动形成维修收费或人工成本。</p>
      <ul v-if="row.labor.length"><li v-for="entry in row.labor" :key="entry.id">
        #{{ entry.id }} · {{ entry.action==='record'?'登记':'更正' }} {{ entry.hours }} 小时<span v-if="entry.original_id"> · 原记录 #{{ entry.original_id }}</span>
        · {{ entry.created_by_name }} · {{ store.localTime(entry.created_at) }}<p>{{ entry.reason }}；依据：{{ entry.evidence }}</p>
      </li></ul>
      <ul v-if="row.parts.length"><li v-for="part in row.parts" :key="part.material_id">{{ part.sku }} · {{ part.material_name }} · 公司耗材 {{ part.quantity }} {{ part.unit }}</li></ul>
      <p v-else>不使用公司耗材。</p>
      <p v-if="row.parts_outbound_id">耗材出库 #{{ row.parts_outbound_id }} · {{ ({draft:'待确认',posted:'已确认',cancelled:'已取消',reversed:'已冲销'})[row.parts_status!] }}</p>
      <ul v-if="row.custody.length"><li v-for="event in row.custody" :key="event.id">{{ event.action==='receive'?'客户物品收件':'交还客户物品' }} {{ event.quantity }} {{ row.frozen_source.unit }} · {{ event.created_by_name }} · {{ store.localTime(event.created_at) }}<p>{{ event.evidence }}</p></li></ul>
    </template>
    <nav class="after-links" aria-label="关联业务单据">
      <RouterLink v-if="store.can('sales.view')" to="/workspace/shipments">原出库 #{{ row.frozen_source.shipment_id }}</RouterLink>
      <RouterLink v-if="row.sales_return_id && store.can('sales.view')" to="/workspace/sales-returns">退货单 #{{ row.sales_return_id }} · {{ row.return_effective?'有效确认':'待确认或已更正' }}</RouterLink>
      <RouterLink v-if="row.replacement_order_id && store.can('sales.view')" to="/workspace/sales-orders">换货订单 #{{ row.replacement_order_id }}</RouterLink>
      <RouterLink v-if="row.parts_outbound_id && store.can('inventory.view')" to="/workspace/warehouse-outbounds">公司耗材出库 #{{ row.parts_outbound_id }}</RouterLink>
      <RouterLink v-if="row.kind==='repair' && store.can('finance.view')" to="/workspace/finance">原订单应收与服务费</RouterLink>
    </nav>
    <template v-if="!compact">
      <h3>方案及操作记录</h3>
      <NCollapse><AppCollapseItem v-for="change in row.changes" :key="change.id" :name="change.id" :title="`${afterSalesCommand[change.action as keyof typeof afterSalesCommand]??({create:'建立申请',edit:'修订方案',inspect_pass:'维修检验合格',inspect_fail:'维修检验不合格',assess_responsibility:'人工责任核定'} as Record<string,string>)[change.action]??change.action} · ${change.changed_by_name} · ${store.localTime(change.created_at)}`">
        <p>原因：{{ change.reason }}</p><p v-if="change.evidence">实际依据：{{ change.evidence }}</p>
        <ul><li v-for="line in afterSalesChanges(change)" :key="line">{{ line }}</li></ul>
      </AppCollapseItem></NCollapse>
    </template>
  </section>
</template>
<style scoped>
.after-evidence{--after-secondary:#50667d;overflow-wrap:anywhere}
:global(:root[data-theme='dark'] .after-evidence){--after-secondary:#9aadc5}
.after-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}
.after-facts dt{color:var(--after-secondary);font-size:12px;margin-bottom:6px}
.after-facts dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
.after-links{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
</style>
