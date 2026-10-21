<script setup lang="ts">
// 详情中的物料身份与摘要统一绘制，参数只取本领域已经授权读取的资料。
import WorkspaceMaterialName from '../../../components/workspace/WorkspaceMaterialName.vue'
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse } from 'naive-ui'
import type { CrmAttachmentKind, CrmQuote } from '../../../../../shared/crm-api'
import { usePiniaAppStore } from '../../../store/app-store'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
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
    <div class="section-heading"><h3>基本资料</h3><div class="crm-toolbar"><slot name="actions" /></div></div>
    <section class="crm-detail-panel">
      <template v-if="quote">
        <dl class="crm-detail-fields">
          <div><dt>单据编号</dt><dd>{{documentLabel(quote)}}</dd></div><div><dt>报价编号</dt><dd>{{quote.reference}}</dd></div>
          <div><dt>状态</dt><dd><AppStatusTag :label="crmQuoteLabel[quote.status]" :tone="quote.status==='approved'||quote.status==='converted'?'success':quote.status==='rejected'?'danger':quote.status==='submitted'?'pending':'neutral'" /></dd></div>
          <div><dt>客户</dt><dd>{{quote.party.customer_name}}</dd></div><div><dt>联系人</dt><dd>{{quote.party.contact_name||'未指定'}}</dd></div><div><dt>联系电话</dt><dd>{{quote.party.phone||'未填写'}}</dd></div>
          <div><dt>邮箱</dt><dd>{{quote.party.email||'未填写'}}</dd></div><div><dt>有效期至</dt><dd>{{quote.valid_until}}</dd></div><div v-if="quote.opportunity_id"><dt>关联商机</dt><dd>{{quote.opportunity_title}}</dd></div>
          <div class="crm-detail-wide"><dt>交货及商务条款</dt><dd>{{quote.terms||'未填写'}}</dd></div>
        </dl>
        <p v-if="quote.expired" role="alert">报价已过期，不能提交、批准或转单。草稿可修订有效期；已批准报价须另建并重新审核。</p>
        <p v-if="!quote.contact_active && !['converted','cancelled'].includes(quote.status)" role="alert">报价联系人已停用，不能提交、批准或转单。请先核实联系人资料；固定报价正文和历史保持原样。</p>
        <!-- 作者记录仍用于溯源，审批资格统一由当前步骤的角色按钮权限决定。 -->
        <p v-if="quote.status==='submitted'">审核、核准与批准按角色的当前步骤按钮权限办理；编制或提交人员拥有权限时也可审批。</p>
        <p v-if="quote.sales_order_id">已转销售订单 {{ relatedDocumentLabel(quote, 'sales_order') }} · {{ quote.sales_order_status==='cancelled' ? '原订单已取消，原报价不能再次转单' : '须继续原订单确认与出库流程' }} · 客户接受依据：{{ quote.acceptance_reference }}</p>
        <AppButton v-if="['approved','converted'].includes(quote.status)" :disabled="busy" @click="store.exportCrmQuotePdf(quote)">导出固定报价 PDF</AppButton>
        <AppButton v-if="quote.sales_order_id && store.can('sales.view')" @click="store.salesNavigation={action:'openOrder',sourceId:quote.sales_order_id!}; store.navigateToRoute('sales')">查看关联销售订单</AppButton>
      </template>
      <dl v-else class="crm-detail-fields"><div><dt>单据编号</dt><dd>{{documentLabel(detail.record)}}</dd></div><div><dt>客户</dt><dd>{{detail.record.customer_name}}</dd></div>
        <div v-if="'owner_name' in detail.record"><dt>负责人</dt><dd>{{detail.record.owner_name}}</dd></div>
        <div v-for="row in snapshot.filter(row=>!['客户编号','联系人编号','商机编号','负责人编号'].includes(row.label))" :key="row.label"><dt>{{row.label}}</dt><dd>{{row.value}}</dd></div></dl>
    </section>
    <WorkspaceTable v-if="quote" title="固定报价明细" :data="quote.lines" :amount-total="quote.total_amount" :min-table-width="1000" :columns="[{key:'sku',title:'物料编码',width:'180'},{key:'material',title:'物料名称',width:'260'},{key:'unit',title:'单位',width:'80'},{key:'quantity',title:'数量',width:'130',align:'right'},{key:'unit_price',title:'单价（元）',width:'140',align:'right'},{key:'line_total',title:'金额（元）',width:'150',align:'right'}]">
      <template #cell-material="{row}"><WorkspaceMaterialName :name="row.material_name" :material-id="row.material_id" :material="store.crmOptions?.materials.find(item => item.id === row.material_id)" /></template>
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

<style scoped>
/* 与公共单据详情采用相同的浅底信息面板和三列字段层级，标题只由外层弹窗显示。 */
.crm-detail-panel { padding:20px; border:1px solid var(--workspace-field-border); border-radius:14px; background:var(--app-modal-surface); }
.crm-detail-fields { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:22px 24px; margin:0; }
.crm-detail-fields dt { margin-bottom:8px; font-size:12px; color:var(--workspace-field-muted); }
.crm-detail-fields dd { margin:0; overflow-wrap:anywhere; white-space:pre-wrap; }
.crm-detail-wide { grid-column:1/-1; }
.section-heading { flex-wrap:wrap; gap:12px; }
.section-heading h3 { margin:0; font-size:15px; }
@media(max-width:850px){.crm-detail-fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:650px){.crm-detail-fields{grid-template-columns:1fr}}
</style>
