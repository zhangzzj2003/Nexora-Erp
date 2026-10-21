<script setup lang="ts" generic="T extends SalesDocument">
import { computed } from 'vue'
import type { Customer } from '../../../../../shared/erp-api'
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import AppButton from '../../../components/app/AppButton.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import SalesRecordFilters from './SalesRecordFilters.vue'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import { salesListColumns, salesBusinessStatus, salesApprovalStatus, salesSummaryGroup } from '../../../utils/sales-presentation'
import type { SalesDocument, SalesDocumentKind, SalesSummaryKey } from '../../../utils/sales-presentation'
import type { SalesRecordFilters as Filters } from '../../../utils/sales-documents'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
const props = defineProps<{kind:SalesDocumentKind; title:string; records:T[]; filtered:T[]; customers:Customer[]; disabled:boolean; localTime:(value:string)=>string}>()
const query = defineModel<string>('query', {required:true})
const filters = defineModel<Filters>('filters', {required:true})
const emit = defineEmits<{view:[row:T]}>()
const columns = computed(()=>salesListColumns(props.kind))
const groups = computed(()=>props.kind === 'order'
  ? [{key:'',label:'全部订单'}, {key:'pending',label:'待处理'}, {key:'active',label:'待交付'}, {key:'completed',label:'已结束'}, {key:'cancelled',label:'已取消'}]
  : [{key:'',label:'全部单据'}, {key:'pending',label:'待处理'}, {key:'completed',label:props.kind==='return'?'已退货':'已出库'}, {key:'cancelled',label:'已取消'}, {key:'reversed',label:'已冲销'}])
const counts = computed(()=>groups.value.map(group=>({...group,
  count:props.records.filter(row=>!group.key || salesSummaryGroup(row)===group.key).length,
  hint:group.key==='completed' && props.kind==='order' ? '全部出库或剩余交付已终止的订单' : `${group.label}的全部可见记录，不随搜索和分页改变`,
  tone:group.key==='reversed'?'reversed' as const:group.key==='completed'?'success' as const:group.key==='pending'||group.key==='active'?'pending' as const:group.key?'neutral' as const:undefined,
})))
// 概览保留客户及日期条件，清除冲突的精确状态；所有条件变化均回到第一页。
function selectGroup(value:string):void { filters.value={...filters.value,group:value as SalesSummaryKey,status:''} }
const rows = computed(()=>props.filtered)
const filterKey = computed(()=>JSON.stringify([query.value,filters.value]))
const {rows:pageRows,page,pageSize,total,changePage}=useLocalPagination(rows,filterKey)
function materialText(row:T):string {return row.lines.map(line=>`${line.material_name} × ${line.quantity} ${line.unit}`).join('；')}
</script>
<template>
  <Teleport defer to="#workspace-page-summary"><WorkspaceSummaryFilters :model-value="filters.group ?? ''" :options="counts" @update:model-value="selectGroup" /></Teleport>
  <WorkspaceTable :title="title" :show-title="false" :columns="columns" :data="pageRows" :min-table-width="1300"
    :pagination="{page,pageSize,total}" @page-change="changePage">
    <template #filters><SalesRecordFilters v-model="filters" v-model:query="query" :customers="customers" :search-label="`搜索${title}`"
      :statuses="kind==='order'?['draft','submitted','approved','rejected','withdrawn','confirmed','partially_shipped','shipped','closed','cancelled']:['draft','submitted','approved','rejected','withdrawn','posted','cancelled','reversed']" /></template>
    <template #actions><slot name="actions" /></template>
    <template #cell-document="{row}"><AppButton variant="text" :disabled="disabled" :aria-label="`查看单据 ${documentLabel(row)} 详情`"
      @click.capture="captureDialogOrigin('sales-business-detail',$event)" @click="emit('view',row)">{{ documentLabel(row) }}</AppButton></template>
    <template #cell-reference="{row}">{{ 'reference' in row ? row.reference || '—' : '—' }}</template>
    <template #cell-source="{row}">{{ relatedDocumentLabel(row,kind==='return'?'shipment':'sales_order') }}</template>
    <template #cell-materials="{row}"><div class="sales-material-summary" :title="materialText(row)"><span>{{ row.lines.slice(0,2).map(line=>line.material_name).join('、') || '—' }}</span><small v-if="row.lines.length>2">+{{ row.lines.length-2 }} 项</small></div></template>
    <template #cell-amount="{row}"><span class="sales-number">{{ 'total_amount' in row ? row.total_amount || '—' : '—' }}</span><small v-if="kind==='return' && row.status==='draft'" class="sales-estimate">预估金额</small></template>
    <template #cell-approval="{row}"><AppStatusTag v-bind="salesApprovalStatus(row)" /></template>
    <template #cell-status="{row}"><AppStatusTag v-bind="salesBusinessStatus(row,kind)" /></template>
    <template #cell-created_at="{row}">{{ localTime(row.created_at) }}</template>
    <template #cell-actions="{row}"><AppButton size="small" :disabled="disabled" :aria-label="`查看单据 ${documentLabel(row)} 详情`"
      @click.capture="captureDialogOrigin('sales-business-detail',$event)" @click="emit('view',row)">查看</AppButton></template>
    <template #empty><strong>{{ records.length?'没有匹配的记录':`暂无${title}记录` }}</strong><span>{{ records.length?'可重置筛选后查看全部记录。':'从右上方新建单据，保存后在这里查看与办理。' }}</span></template>
  </WorkspaceTable>
</template>
<style scoped>
/* 摘要只展示两种物料，完整数量与履约信息留在明细表，避免多行订单撑高整张列表。 */
.sales-material-summary { display:flex; align-items:center; gap:8px; min-width:0; }
.sales-material-summary > span { overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow-wrap:anywhere; }
.sales-material-summary > small { flex-shrink:0; color:var(--workspace-field-muted); }
.sales-number { font-variant-numeric:tabular-nums; }
.sales-estimate { display:block; color:var(--workspace-field-muted); font-size:12px; }
</style>
