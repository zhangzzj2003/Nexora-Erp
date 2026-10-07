<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import type { QualityEvidence } from '../../../../../shared/quality-api'
import { qualityChanges,qualityCommand,qualityStatus,qualityTreatment } from './quality-display'
import { usePiniaAppStore } from '../../../store/app-store'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
defineProps<{row:QualityEvidence;compact?:boolean}>()
const store=usePiniaAppStore()
</script>
<template>
  <section class="quality-evidence" :aria-label="`处置 ${row.reference} 的证据`">
    <h3>{{ documentLabel(row) }} · {{ row.reference }} · {{ qualityStatus[row.status] }} · v{{ row.version }}</h3>
    <dl class="quality-facts">
      <div><dt>原质检与工单</dt><dd>完工单 {{ relatedDocumentLabel(row, 'completion') }} · 工单 {{ relatedDocumentLabel(row, 'work_order', row.frozen_source) }}</dd></div>
      <div><dt>成品</dt><dd>{{ row.frozen_source.product_sku }} · {{ row.frozen_source.product_name }}</dd></div>
      <div><dt>原检验结果</dt><dd>报工 {{ row.frozen_source.reported_quantity }} · 合格 {{ row.frozen_source.accepted_quantity }} · 不合格 {{ row.frozen_source.rejected_quantity }} {{ row.frozen_source.product_unit }}</dd></div>
      <div><dt>本次处置</dt><dd>{{ row.kind==='scrap'?'报废':'返工' }} {{ row.quantity }} {{ row.frozen_source.product_unit }}</dd></div>
      <div><dt>成本处理</dt><dd>{{ qualityTreatment[row.loss_treatment] }}</dd></div>
      <div><dt>原质检依据</dt><dd>{{ row.frozen_source.qc_note }} · {{ store.localTime(row.frozen_source.inspected_at) }}</dd></div>
      <div><dt>缺陷记录</dt><dd>{{ row.defect }}</dd></div><div><dt>处置说明</dt><dd>{{ row.action_note }}</dd></div>
    </dl>
    <template v-if="row.kind==='rework'">
      <h4>返工追加材料</h4>
      <ul v-if="row.materials.length"><li v-for="line in row.materials" :key="line.material_id">{{ line.sku }} · {{ line.material_name }} · {{ line.quantity }} {{ line.unit }}</li></ul>
      <p v-else>无追加材料；下达后可登记人工、制造费用并重新报工检验。</p>
      <p>返工目标仓库 #{{ row.warehouse_id }}。原不合格品不会增加可用库存，合格品按返工工单重新检验入库。</p>
      <p v-if="row.rework_order_id">已关联返工工单 {{ relatedDocumentLabel(row, 'rework_order') }}。<RouterLink v-if="store.can('production.view')" to="/workspace/work-orders">查看生产工单</RouterLink></p>
    </template>
    <template v-if="!compact">
      <p v-if="row.cost_allocation">原工单结算 {{ relatedDocumentLabel(row.cost_allocation, 'settlement') }}<template v-if="row.cost_visible"> · 本处置分摊 {{ row.cost_allocation.amount }} 元（人民币）</template>。<RouterLink v-if="store.can('production_cost.view')" to="/workspace/production-costs">查看生产成本</RouterLink></p>
      <p v-else-if="row.status==='posted'">处置已确认，来源成本尚未固定；原工单全部报工和处置后，须由财务结算。</p>
      <h3>操作与更正证据</h3>
      <NCollapse><AppCollapseItem v-for="change in row.changes" :key="change.id" :name="change.id" :title="`${qualityCommand[change.action as keyof typeof qualityCommand] ?? (change.action==='create'?'建立处置':'修订处置')} · ${change.changed_by_name} · ${store.localTime(change.created_at)}`">
        <p>原因：{{ change.reason }}</p>
        <dl class="quality-facts"><div v-for="item in qualityChanges(change.before,change.after)" :key="item.name"><dt>{{ item.name }}</dt><dd>之前：{{ item.before }}<br>之后：{{ item.after }}</dd></div></dl>
      </AppCollapseItem></NCollapse>
    </template>
  </section>
</template>
<style scoped>
.quality-evidence{--quality-secondary:#50667d;overflow-wrap:anywhere}
:global(:root[data-theme='dark'] .quality-evidence){--quality-secondary:#9aadc5}
.quality-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}
.quality-facts dt{color:var(--quality-secondary);font-size:12px;margin-bottom:6px}
.quality-facts dd{margin:0;overflow-wrap:anywhere;white-space:pre-wrap}
</style>
