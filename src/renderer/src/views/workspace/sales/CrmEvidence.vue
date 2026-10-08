<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse } from 'naive-ui'
import type { CrmAttachmentKind, CrmQuote } from '../../../../../shared/crm-api'
import { usePiniaAppStore } from '../../../store/app-store'
import AppButton from '../../../components/app/AppButton.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import CrmQuoteAttachments from './CrmQuoteAttachments.vue'
import CrmRecordAttachments from './CrmRecordAttachments.vue'
import { crmKindLabel,crmAuditLabel,crmQuoteLabel,crmSnapshotRows } from './crm-display'
const store=usePiniaAppStore()
const {crmDetail:detail,crmChanges:changes,busy}=storeToRefs(store)
const quote=computed(()=>detail.value?.kind==='quote' ? detail.value.record as CrmQuote : null)
const recordAttachmentKind=computed<CrmAttachmentKind | null>(()=>
  detail.value && detail.value.kind!=='quote' ? detail.value.kind : null)
const snapshot=computed(()=>detail.value ? crmSnapshotRows(detail.value.kind,detail.value.record as unknown as Record<string,unknown>) : [])
function auditLines(source:Record<string,unknown>): {material_name:string; quantity:string; unit_price:string; line_total:string}[] {
  return Array.isArray(source.lines) ? source.lines.map(row=>({material_name:String(row.material_name??''),quantity:String(row.quantity??''),unit_price:String(row.unit_price??''),line_total:String(row.line_total??'')})) : []
}
</script>
<template>
  <section v-if="detail" class="stack crm-evidence" aria-label="记录详情与审计">
    <section class="card">
      <div class="section-heading"><h2>{{ crmKindLabel[detail.kind] }}详情 · {{ documentLabel(detail.record) }}</h2><AppButton @click="store.clearCrmDetail()">关闭详情</AppButton></div>
      <template v-if="quote">
        <h3>{{ documentLabel(quote) }} · {{ quote.reference }} · {{ crmQuoteLabel[quote.status] }}</h3>
        <p>{{ quote.party.customer_name }} · {{ quote.party.contact_name || '未指定联系人' }} · {{ quote.party.phone || '未填写电话' }} · {{ quote.party.email || '未填写邮箱' }}</p>
        <p>人民币 {{ quote.total_amount }} 元 · 有效至 {{ quote.valid_until }} · 商机：{{ quote.opportunity_title }}</p>
        <p v-if="quote.expired" role="alert">报价已过期，不能提交、批准或转单。草稿可修订有效期；已批准报价须另建并重新审核。</p>
        <p v-if="!quote.contact_active && !['converted','cancelled'].includes(quote.status)" role="alert">报价联系人已停用，不能提交、批准或转单。请先核实联系人资料；固定报价正文和历史保持原样。</p>
        <!-- 作者记录仍用于溯源，审批资格统一由当前步骤的角色按钮权限决定。 -->
        <p v-if="quote.status==='submitted'">审核、核准与批准按角色的当前步骤按钮权限办理；编制或提交人员拥有权限时也可审批。</p>
        <p>{{ quote.terms || '未填写商务条款' }}</p>
        <p v-if="quote.sales_order_id">已转销售订单 {{ relatedDocumentLabel(quote, 'sales_order') }} · {{ quote.sales_order_status==='cancelled' ? '原订单已取消，原报价不能再次转单' : '须继续原订单确认与出库流程' }} · 客户接受依据：{{ quote.acceptance_reference }}</p>
        <AppButton v-if="['approved','converted'].includes(quote.status)" :disabled="busy" @click="store.exportCrmQuotePdf(quote)">导出固定报价 PDF</AppButton>
        <AppButton v-if="quote.sales_order_id && store.can('sales.view')" @click="store.navigateToRoute('sales')">打开销售订单列表</AppButton>
      </template>
      <dl v-else class="crm-facts"><template v-for="row in snapshot" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
    </section>
    <WorkspaceTable v-if="quote" title="固定报价明细" :data="quote.lines" :min-table-width="750" :columns="[{key:'material',title:'物料'},{key:'quantity',title:'数量'},{key:'unit_price',title:'单价（元）'},{key:'line_total',title:'金额（元）'}]">
      <template #cell-material="{row}">{{ row.sku }} · {{ row.material_name }}<span class="crm-secondary muted">{{ row.unit }}</span></template>
    </WorkspaceTable>
    <CrmQuoteAttachments v-if="quote" :quote-id="quote.id" />
    <CrmRecordAttachments v-if="recordAttachmentKind" :kind="recordAttachmentKind" :record-id="detail.record.id" :record-version="detail.record.version" />
    <section class="card">
      <h3>变更与操作依据</h3>
      <NCollapse><AppCollapseItem v-for="change in changes" :key="change.id" :name="String(change.id)" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${crmAuditLabel[change.action] ?? '变更'} · ${change.reason}`">
        <div class="crm-audit-grid"><section v-for="(source,index) in [change.before,change.after]" :key="index">
          <h4>{{ index===0 ? '变更前' : '变更后' }}</h4><p v-if="!source">首次建立，无原版本。</p>
          <template v-else><dl class="crm-facts"><template v-for="row in crmSnapshotRows(change.entity_kind,source)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
            <ul v-if="auditLines(source).length"><li v-for="(line,lineIndex) in auditLines(source)" :key="lineIndex">{{ line.material_name }} · 数量 {{ line.quantity }} · 单价 {{ line.unit_price }} 元 · 金额 {{ line.line_total }} 元</li></ul>
          </template>
        </section></div>
      </AppCollapseItem></NCollapse>
      <p v-if="!changes.length">暂未读取到变更记录，请重新读取详情。</p>
    </section>
  </section>
</template>
