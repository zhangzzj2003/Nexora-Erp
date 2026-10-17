<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import AppModal from '../app/AppModal.vue'
import AppButton from '../app/AppButton.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import WorkspaceDocumentDialog from './WorkspaceDocumentDialog.vue'
import DocumentApprovalProgress from './DocumentApprovalProgress.vue'
import { usePiniaAppStore } from '../../store/app-store'
import InventoryMaterialFacts from './InventoryMaterialFacts.vue'
import InventoryMaterialLedger from './InventoryMaterialLedger.vue'
import WorkspaceMaterialParameters from './WorkspaceMaterialParameters.vue'
import { materialParameterSource } from '../../utils/material-parameter-source'
import { isNegativeStock } from '../../../../shared/stock-overview'
import { documentApprovalLayout } from '../../utils/document-approval-layout'
import { movementTypeLabel } from '../../utils/formatters'
import { relatedDocumentLabel } from '../../../../shared/document-numbering'
import { ledgerTime } from '../../utils/inventory-ledger-presentation'
import { materialFlowApprovalExecutionHint } from '../../utils/material-flow-progress'

const store = usePiniaAppStore()
const { connectionLost, roles, stockMaterialMode, stockMaterialSnapshot, stockMaterialLoading, stockMaterialError,
  ledgerMaterialTarget: materialTarget, ledgerMaterialDetail: material,
  ledgerMaterialLoading: materialLoading, ledgerMaterialError: materialError,
  ledgerMaterialRowsLoading: rowsLoading, ledgerMaterialRowsError: rowsError,
  ledgerDocumentTarget: documentTarget, ledgerDocumentRecord: document,
  ledgerDocumentLoading: documentLoading, ledgerDocumentError: documentError } = storeToRefs(store)
// 资料、首屏流水与全仓分布共同构成首屏；其中任一失败都不展开残缺详情。
const materialReady = computed(() => !!material.value && !materialLoading.value && !rowsLoading.value
  && (!stockMaterialMode.value || (!!stockMaterialSnapshot.value && !stockMaterialLoading.value)))
const materialLoadError = computed(() => materialError.value || rowsError.value || (stockMaterialMode.value ? stockMaterialError.value : ''))
const layout = computed(() => documentApprovalLayout(document.value))
// 普通领料按权限直接签收，仅更正有独立审批；不能把无审批记录展示为待送审。
const directReceipt = computed(() => document.value?.document_type === 'MaterialReceipt' && document.value.intent === 'execute')
const executionHint = computed(() => materialFlowApprovalExecutionHint(document.value))
const warehouseColumns = [{ key: 'warehouse_code', title: '仓库编号', width: '140' }, { key: 'warehouse_name', title: '仓库名称', width: '240' }, { key: 'quantity', title: '物料数量', width: '150', align: 'right' as const }, { key: 'actions', title: '操作', width: '130' }]
const documentColumns = [{ key: 'label', title: '物料编号 / 名称', width: '440' }, { key: 'value', title: '数量 / 单位', width: '160' }]
</script>

<template>
  <!-- 三个库存入口统一上方资料、下方明细；关闭后回到原筛选和页码。 -->
  <AppModal :show="!!materialTarget" origin-key="inventory-material" :ready="materialReady" :load-error="materialLoadError" @update:show="value => { if (!value) store.closeLedgerMaterial() }" preset="card"
    :title="`物料详情 · ${materialTarget?.sku ?? ''}`" :style="{ width: 'min(1280px, calc(100vw - 32px))' }">
    <div class="ledger-material-content">
      <InventoryMaterialFacts compact />
      <section v-if="stockMaterialMode" class="stock-distribution" aria-label="各仓库库存">
        <div class="stock-distribution-heading"><h3>各仓库库存</h3>
          <span v-if="stockMaterialSnapshot">全仓合计 <strong>{{ stockMaterialSnapshot.total_quantity }} {{ stockMaterialSnapshot.unit }}</strong></span>
        </div>
        <p class="ledger-scope">展示当前各仓库数量，保留已清零的历史仓库；点击“查看流水”筛选下方明细。</p>
        <WorkspaceTable title="各仓库库存" :show-title="false" :columns="warehouseColumns"
          :data="stockMaterialSnapshot?.warehouses ?? []" :loading="stockMaterialLoading" :error="stockMaterialError" :min-table-width="660">
          <template #cell-quantity="{ row }"><strong :class="{ 'ledger-detail-error': isNegativeStock(row.quantity) }">{{ row.quantity }} {{ stockMaterialSnapshot?.unit }}</strong></template>
          <template #cell-actions="{ row }"><AppButton variant="secondary" size="small" :disabled="connectionLost || stockMaterialLoading || !!stockMaterialError || rowsLoading" @click="store.selectStockMaterialWarehouse(row.warehouse_id)">查看流水</AppButton></template>
          <template #empty>该物料尚无已确认的库存流水，各仓库当前数量为 0。</template>
          <template #errorActions><AppButton :disabled="connectionLost || stockMaterialLoading" @click="store.loadStockMaterial()">重新读取仓库分布</AppButton></template>
        </WorkspaceTable>
      </section>
      <InventoryMaterialLedger :overview="stockMaterialMode" />
    </div>
    <template #footer><div class="ledger-detail-actions"><AppButton @click="store.closeLedgerMaterial()">关闭</AppButton></div></template>
  </AppModal>

  <!-- 只读单据使用公共详情外壳；不挂载审批表单或业务写入按钮。 -->
  <WorkspaceDocumentDialog :show="!!documentTarget" origin-key="inventory-document" :ready="!documentLoading && !!document" :load-error="documentError" :title="`单据详情 · ${documentTarget ? relatedDocumentLabel(documentTarget, 'source') : ''}`"
    read-only :data="layout.lines" :columns="documentColumns" :show-lines="!!document && layout.showLines" :min-table-width="600"
    @update:show="value => { if (!value) store.closeLedgerDocument() }">
    <template #beforeBasicInfo>
      <p v-if="documentLoading" role="status">正在读取单据详情…</p>
      <p v-if="documentError" role="alert" class="ledger-detail-error">{{ documentError }}</p>
      <DocumentApprovalProgress v-if="document && !directReceipt" :record="document" :roles="roles" :local-time="ledgerTime" :execution-hint="executionHint" />
      <p v-if="document && !document.content_matches" class="ledger-scope">以下为原单送审内容，后续变更请结合原单记录核对。</p>
    </template>
    <template #basicInfo>
      <template v-if="document && documentTarget">
        <div class="document-detail-field"><span>单据类型</span><strong>{{ movementTypeLabel(documentTarget.source_type) }}</strong></div>
        <div class="document-detail-field"><span>单据编号</span><strong>{{ document.document_no || `#${document.document_id}` }}</strong></div>
        <div class="document-detail-field"><span>关联流水</span><strong>#{{ documentTarget.id }} · 明细 #{{ documentTarget.source_line_id }}</strong></div>
        <div v-for="(item, index) in layout.basic" :key="index" class="document-detail-field"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><WorkspaceMaterialParameters v-if="item.material_id" :material="materialParameterSource(item.material_id,item.material)" current-reference /></div>
        <div v-if="document.reversal_reason" class="document-detail-field"><span>冲销原因</span><strong>{{ document.reversal_reason }}</strong></div>
      </template>
    </template>
    <template #cell-label="{ row }"><strong>{{ row.label }}</strong><WorkspaceMaterialParameters v-if="row.material_id" :material="materialParameterSource(row.material_id,row.material)" current-reference /></template>
    <template #cell-value="{ row }">{{ row.value }}</template>
    <template #footer><div class="ledger-detail-actions">
      <AppButton v-if="documentError" :disabled="connectionLost || documentLoading" @click="store.loadLedgerDocument()">重新读取单据</AppButton>
      <AppButton @click="store.closeLedgerDocument()">关闭</AppButton>
    </div></template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 共用同一正文滚动区；操作区的分割线由公共卡片弹窗样式统一提供。 */
.ledger-scope { color: var(--workspace-field-muted); line-height: 1.7; }
.ledger-scope small { display: block; }
.ledger-detail-actions { display: flex; justify-content: flex-end; gap: 10px; margin-left: auto; }
.ledger-detail-error { color: var(--app-danger, #b94438); }
.stock-distribution { margin: 24px 0; }
.stock-distribution-heading { display: flex; align-items: baseline; flex-wrap: wrap; justify-content: space-between; gap: 12px; }
.stock-distribution-heading h3 { margin: 0; }
.stock-distribution-heading span { color: var(--workspace-field-muted); }
</style>
