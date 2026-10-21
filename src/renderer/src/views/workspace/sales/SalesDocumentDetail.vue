<script setup lang="ts">
import {computed} from 'vue'
import WorkspaceMaterialName from '../../../components/workspace/WorkspaceMaterialName.vue'
import type {MaterialChoice} from '../../../../../shared/material-api'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import {documentLabel,relatedDocumentLabel} from '../../../../../shared/document-numbering'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api'
import {salesBusinessStatus,salesApprovalStatus,salesLineColumns} from '../../../utils/sales-presentation'
import type {SalesDocument,SalesDocumentKind} from '../../../utils/sales-presentation'
const props=defineProps<{record:SalesDocument|null;kind:SalesDocumentKind;title:string;busy:boolean;disabled:boolean;localTime:(value:string)=>string;materials?:MaterialChoice[]}>()
const emit=defineEmits<{close:[]}>()
const columns=computed(()=>salesLineColumns(props.kind))
// 明细只映射已获授权的原始响应，不从基础物料价格推导单据金额。
const lines=computed(()=>props.record?.lines.map(line=>{
  const result:Record<string,string>={}
  for(const [key,value] of Object.entries(line)) result[key]=value==null||value===''?'—':String(value)
  const lots='physical_lots' in line ? line.physical_lots??[] : []
  if(props.kind!=='order') result.physical_lots=lots.length
    ? lots.map(lot=>`${lot.code} · ${lot.quantity} ${line.unit} · ${physicalLotKindLabel(lot.source_kind)}`).join('；')
    : props.record?.status==='posted'?'普通确认未指定实物批次，数量在批次核对页显示为差额。':'待确认'
  return result
})??[])
</script>
<template>
  <WorkspaceDocumentDialog origin-key="sales-business-detail" :show="!!record" :title="`${title}详情`" read-only :busy="busy" :disabled="disabled"
    :data="lines" :columns="columns" :min-table-width="1100" :amount-total="record && 'total_amount' in record ? record.total_amount : undefined"
    @update:show="value=>{if(!value)emit('close')}" @invalidated="emit('close')">
    <template #basicInfo><template v-if="record">
      <div class="document-detail-field"><span>单据编号</span><strong>{{documentLabel(record)}}</strong></div>
      <div class="document-detail-field"><span>客户</span><strong>{{record.customer_name}}</strong></div>
      <div class="document-detail-field"><span>业务状态</span><AppStatusTag v-bind="salesBusinessStatus(record,kind)" /></div>
      <div v-if="'warehouse_name' in record" class="document-detail-field"><span>{{kind==='return'?'退货仓库':'出库仓库'}}</span><strong>{{record.warehouse_name}}</strong></div>
      <div v-if="kind!=='order'" class="document-detail-field"><span>{{kind==='return'?'原出库单':'销售订单'}}</span><strong>{{relatedDocumentLabel(record,kind==='return'?'shipment':'sales_order')}}</strong></div>
      <div class="document-detail-field"><span>审批状态</span><AppStatusTag v-bind="salesApprovalStatus(record)" /></div>
      <div class="document-detail-field"><span>创建人</span><strong>{{record.created_by_name||'—'}}</strong></div>
      <div class="document-detail-field"><span>创建时间</span><strong>{{localTime(record.created_at)}}</strong></div>
      <div class="document-detail-field"><span>{{'reason' in record?'退货原因':'参考单号'}}</span><strong>{{('reason' in record?record.reason:record.reference)||'—'}}</strong></div>
      <div v-if="'reversal_id' in record && record.reversal_id" class="document-detail-field document-basic-extra"><span>冲销记录</span><strong>{{record.reversal_reason}} · {{record.reversed_by_name}} · {{record.reversed_at?localTime(record.reversed_at):'—'}}</strong></div>
      <p v-if="kind==='return' && record.status==='draft'" class="document-basic-extra muted">当前为预估退货金额，确认后以原出库分摊并固定的金额为准。</p>
    </template></template>
    <template #documentActions><slot name="actions" /></template>
    <template v-for="column in columns" :key="column.key" #[`cell-${column.key}`]="{row}"><WorkspaceMaterialName v-if="column.key==='material_name'" :name="row.material_name" :material-id="Number(row.material_id)" :material="materials?.find(item=>item.id===Number(row.material_id))" /><span v-else class="sales-detail-value">{{row[column.key]}}</span></template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 长保修依据与批次允许完整换行；数字沿用全站表格字体和对齐。 */
.sales-detail-value { white-space:pre-wrap; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
</style>
