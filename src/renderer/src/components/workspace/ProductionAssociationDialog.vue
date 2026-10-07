<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../store/app-store'
import WorkspaceDocumentDialog from './WorkspaceDocumentDialog.vue'
import AppButton from '../app/AppButton.vue'
import { documentLabel } from '../../../../shared/document-numbering'

// 共用单据表格弹窗只读展示关联，不提供领料、补证或批准等写入动作。
const store = usePiniaAppStore()
const {productionAssociationTarget: target, productionAssociationRecord: record,
  productionAssociationLoading: loading, productionAssociationError: error, connectionLost} = storeToRefs(store)
const selectedCompletion = computed(() => record.value?.target.kind === 'completion'
  ? record.value.completions.find(row => row.id === record.value?.target.id) : null)
const columns = [{key:'material',title:'物料',width:'170px'},{key:'quantity',title:'需求与净领料',width:'160px'},
  {key:'documents',title:'领料与退料单据',width:'300px'},{key:'sources',title:'来源证据与排查参考',width:'440px'}]
const labels: Record<string,string> = {draft:'草稿',inspected:'已质检',posted:'已确认',reversed:'已冲销',
  cancelled:'已取消',released:'已下达',in_progress:'生产中',completed:'已完工'}
</script>

<template>
  <WorkspaceDocumentDialog :show="!!target" :title="`生产关联单据${record ? ` · ${documentLabel(selectedCompletion ?? record.work_order)}` : ''}`"
    :data="record?.components ?? []" :columns="columns" :read-only="true" :min-table-width="1070"
    lines-title="物料需求与实际单据" empty-text="暂无组件需求。"
    hint="本查询展示工单层面的领退料及登记来源，不能证明某台产品或某次分批完工的实际耗用。"
    @update:show="value=>{if(!value)store.closeProductionAssociations()}">
    <template #basicInfo>
      <p v-if="loading" role="status">正在读取生产关联…</p>
      <p v-if="error" role="alert">{{error}}</p>
      <template v-if="record">
        <p>工单 <strong>{{documentLabel(record.work_order)}}</strong> · {{record.work_order.product_name}}（{{record.work_order.product_sku}}）<br>
          {{labels[record.work_order.status] ?? '历史状态'}} · 目标 {{record.work_order.target_quantity}} · BOM #{{record.bom.id}} / V{{record.bom.version}}
        </p>
        <p>完工单据<br><span v-for="completion in record.completions" :key="completion.id" class="association-line">
          {{documentLabel(completion)}} · {{labels[completion.status] ?? '历史状态'}} · 报工 {{completion.reported_quantity}} / 合格 {{completion.accepted_quantity ?? '待检'}}
          <strong v-if="selectedCompletion?.id===completion.id">（当前查询）</strong><span v-if="completion.reversal_reason"> · {{completion.reversal_reason}}</span>
        </span><span v-if="!record.completions.length">暂无完工记录</span></p>
        <p v-if="!record.inventory_visible">入库与供应商来源需库存查看权限，本查询未返回这些信息。</p>
        <p v-if="record.references_included">采购参考范围：截至 {{store.localTime(record.reference_cutoff)}}，每个物料最近 {{record.reference_limit}} 条有效入库。参考可能已耗尽或来自其他仓库，不能证明实际领用。</p>
      </template>
      <div class="form-actions">
        <AppButton type="button" size="small" :disabled="loading || connectionLost" @click="store.loadProductionAssociations(record?.references_included ?? false)">刷新关联</AppButton>
        <AppButton v-if="record?.inventory_visible && !record.references_included" type="button" variant="secondary" size="small" :disabled="loading || connectionLost"
          @click="store.loadProductionAssociations(true)">查看同物料采购参考</AppButton>
      </div>
    </template>
    <template #cell-material="{row}"><strong>{{row.name}}</strong><p class="muted">{{row.sku}} · {{row.unit}}</p></template>
    <template #cell-quantity="{row}">需求 {{row.required_quantity}}<br>有效净领 {{row.net_issued_quantity}}<p class="muted">净领不等于单台产品实际耗用。</p></template>
    <template #cell-documents="{row}">
      <div v-for="issue in row.issues" :key="issue.line_id" class="association-entry">
        <strong>{{documentLabel(issue)}} · {{labels[issue.status] ?? '历史状态'}}</strong><p>原领 {{issue.quantity}} · 有效退回 {{issue.returned_quantity}}</p>
        <p v-if="issue.reversal_reason">冲销依据：{{issue.reversal_reason}}</p>
        <p v-for="returned in issue.returns" :key="returned.line_id">退料 {{documentLabel(returned)}} · {{labels[returned.status] ?? '历史状态'}} · {{returned.quantity}}<span v-if="returned.reversal_reason"> · {{returned.reversal_reason}}</span></p>
      </div><p v-if="!row.issues.length" class="muted">尚无领料单据。</p>
    </template>
    <template #cell-sources="{row}">
      <div v-for="issue in row.issues.filter(item=>item.status==='posted'||item.status==='reversed')" :key="issue.line_id" class="association-entry">
        <strong>{{documentLabel(issue)}} 的领料登记<span v-if="!issue.effective">（原历史，已失效）</span></strong>
        <p v-if="issue.unassigned_quantity!==null && Number(issue.unassigned_quantity)>0">{{issue.unassigned_quantity}} {{row.unit}} 缺少固定批次分配证据，无法确认采购来源。</p>
        <p v-for="source in issue.sources" :key="source.lot_id">
          {{source.lot_code}} · 原领分配 {{source.quantity}} {{row.unit}} · {{source.evidence_kind==='supplement'?'事后补证':'确认时登记'}}<br>
          <template v-if="source.supplier_id!==null">采购入库 {{source.source_document_no ?? `#${source.source_id}`}} · {{source.supplier_name}}<span v-if="source.receipt_reversed">（原入库已冲销）</span></template>
          <template v-else>未确认采购入库来源</template>
          <span v-if="source.origin_movement_id"> · 原始流水 #{{source.origin_movement_id}}</span>
        </p><p v-if="issue.sources.length">上述为领料时分配，退料另列；没有按完工单或单台产品分配净耗用。</p>
      </div>
      <div v-if="row.purchase_references.length" class="association-entry">
        <strong>同物料排查参考（未经证实使用）</strong>
        <p v-for="reference in row.purchase_references" :key="reference.line_id">入库 {{reference.document_no ?? `#${reference.receipt_id}`}} · {{reference.supplier_name}} · 原入库量 {{reference.quantity}} {{row.unit}}</p>
      </div>
    </template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 长来源证据沿共享表格滚动；独立分组避免参考记录和已登记来源混读。 */
.association-line {display:block;margin-top:8px}
.association-entry + .association-entry {border-top:1px solid var(--workspace-field-border);padding-top:12px;margin-top:12px}
.association-entry p {margin:8px 0;overflow-wrap:anywhere}
</style>
