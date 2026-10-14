<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NTabs, NTabPane } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import WorkspaceDocumentDialog from './WorkspaceDocumentDialog.vue'
import DocumentApprovalProgress from './DocumentApprovalProgress.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { materialChoiceFacts } from '../../utils/material-selection'
import { documentApprovalLayout } from '../../utils/document-approval-layout'
import { movementTypeLabel } from '../../utils/formatters'
import { relatedDocumentLabel } from '../../../../shared/document-numbering'
import { ledgerMovementColumns, ledgerTime } from '../../utils/inventory-ledger-presentation'

const store = usePiniaAppStore()
const { connectionLost, materialCategories, warehouses, roles,
  ledgerMaterialTarget: materialTarget, ledgerMaterialDetail: material,
  ledgerMaterialLoading: materialLoading, ledgerMaterialError: materialError,
  ledgerMaterialQuery: query, ledgerMaterialResult: result,
  ledgerMaterialRowsLoading: rowsLoading, ledgerMaterialRowsError: rowsError,
  ledgerDocumentTarget: documentTarget, ledgerDocumentRecord: document,
  ledgerDocumentLoading: documentLoading, ledgerDocumentError: documentError } = storeToRefs(store)
const tab = ref('details')
watch(materialTarget, () => { tab.value = 'details' }, { flush: 'sync' })
const facts = computed(() => material.value ? [
  { key: 'sku', label: '物料编号', value: material.value.sku },
  { key: 'name', label: '物料名称', value: material.value.name },
  ...materialChoiceFacts(material.value, materialCategories.value),
  ...materialChoiceFacts(material.value, materialCategories.value, true)
] : [])
const scope = computed(() => {
  if (!query.value) return ''
  const q = query.value
  const warehouse = q.warehouse_id === null ? '全部仓库' : warehouses.value.find(row => row.id === q.warehouse_id)?.name ?? '所选仓库'
  const dates = !q.from_date && !q.to_date ? '全部日期' : `${q.from_date || '最早'} 至 ${q.to_date || '至今'}`
  return `${warehouse} · ${dates} · ${q.source_type ? movementTypeLabel(q.source_type) : '全部来源'}`
})
const layout = computed(() => documentApprovalLayout(document.value))
const documentColumns = [{ key: 'label', title: '物料编号 / 名称', width: '440' }, { key: 'value', title: '数量 / 单位', width: '160' }]
</script>

<template>
  <!-- 资料与台账在同一弹窗切换，关闭后回到原筛选和页码。 -->
  <NModal :show="!!materialTarget" @update:show="value => { if (!value) store.closeLedgerMaterial() }" preset="card"
    :title="`物料详情 · ${materialTarget?.sku ?? ''}`" :style="{ width: 'min(1280px, calc(100vw - 32px))' }">
    <div class="ledger-material-content">
      <NTabs v-model:value="tab" type="line" animated>
        <NTabPane name="details" tab="物料详情">
          <p v-if="materialLoading" role="status">正在读取物料详情…</p>
          <div v-else-if="materialError" role="alert" class="ledger-detail-error">
            <p>{{ materialError }}</p><AppButton :disabled="connectionLost" @click="store.loadLedgerMaterial()">重新读取物料</AppButton>
          </div>
          <dl v-else-if="material" class="ledger-material-facts">
            <div v-for="fact in facts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div>
          </dl>
        </NTabPane>
        <NTabPane name="ledger" tab="台账明细">
          <p class="ledger-scope">{{ scope }}<small>按所选仓库、物料及日期核对流水</small></p>
          <WorkspaceTable v-if="query" title="物料台账明细" :show-title="false" :data="result.rows" :columns="ledgerMovementColumns"
            :loading="rowsLoading" :error="rowsError" :min-table-width="898"
            :pagination="{ page: query.page, pageSize: query.page_size, total: result.total, disabled: connectionLost }"
            @page-change="store.queryLedgerMaterial">
            <template #cell-time="{ row }"><span class="ledger-time">{{ ledgerTime(row.created_at) }}</span></template>
            <template #cell-operator="{ row }">{{ row.created_by_name || '—' }}</template>
            <template #cell-source_type="{ row }">{{ movementTypeLabel(row.source_type) }}</template>
            <template #cell-source_document="{ row }"><AppButton variant="text" :disabled="connectionLost"
              :aria-label="`查看单据 ${relatedDocumentLabel(row, 'source')} 详情`" @click="store.openLedgerDocument(row)">{{ relatedDocumentLabel(row, 'source') }}</AppButton></template>
            <template #cell-quantity="{ row }">{{ row.quantity.startsWith('-') ? '' : '+' }}{{ row.quantity }} {{ row.unit }}</template>
            <template #cell-balance="{ row }">{{ row.balance_quantity }} {{ row.unit }}</template>
            <template #empty>当前范围内暂无该物料的库存流水。</template>
            <template #errorActions><AppButton :disabled="connectionLost || rowsLoading" @click="store.queryLedgerMaterial(query.page)">重新查询</AppButton></template>
            <template #footer v-if="!rowsLoading && !rowsError && result.groups.length">
              <!-- 使用服务端完整期间汇总，不用本页流水相加代替期初期末。 -->
              <div class="ledger-balances"><p v-for="group in result.groups" :key="group.warehouse_id">
                <strong>{{ group.warehouse_name }}</strong><span>期初 {{ group.opening_quantity }} {{ group.unit }}</span>
                <span>期末 {{ group.closing_quantity }} {{ group.unit }}</span>
              </p></div>
            </template>
          </WorkspaceTable>
        </NTabPane>
      </NTabs>
    </div>
    <template #footer><div class="ledger-detail-actions"><AppButton @click="store.closeLedgerMaterial()">关闭</AppButton></div></template>
  </NModal>

  <!-- 只读单据使用公共详情外壳；不挂载审批表单或业务写入按钮。 -->
  <WorkspaceDocumentDialog :show="!!documentTarget" :title="`单据详情 · ${documentTarget ? relatedDocumentLabel(documentTarget, 'source') : ''}`"
    read-only :data="layout.lines" :columns="documentColumns" :show-lines="!!document && layout.showLines" :min-table-width="600"
    @update:show="value => { if (!value) store.closeLedgerDocument() }">
    <template #beforeBasicInfo>
      <p v-if="documentLoading" role="status">正在读取单据详情…</p>
      <p v-if="documentError" role="alert" class="ledger-detail-error">{{ documentError }}</p>
      <DocumentApprovalProgress v-if="document" :record="document" :roles="roles" :local-time="ledgerTime" />
      <p v-if="document && !document.content_matches" class="ledger-scope">以下为原单送审内容，后续变更请结合原单记录核对。</p>
    </template>
    <template #basicInfo>
      <template v-if="document && documentTarget">
        <div class="document-detail-field"><span>单据类型</span><strong>{{ movementTypeLabel(documentTarget.source_type) }}</strong></div>
        <div class="document-detail-field"><span>单据编号</span><strong>{{ document.document_no || `#${document.document_id}` }}</strong></div>
        <div class="document-detail-field"><span>关联流水</span><strong>#{{ documentTarget.id }} · 明细 #{{ documentTarget.source_line_id }}</strong></div>
        <div v-for="(item, index) in layout.basic" :key="index" class="document-detail-field"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
        <div v-if="document.reversal_reason" class="document-detail-field"><span>冲销原因</span><strong>{{ document.reversal_reason }}</strong></div>
      </template>
    </template>
    <template #cell-label="{ row }">{{ row.label }}</template>
    <template #cell-value="{ row }">{{ row.value }}</template>
    <template #footer><div class="ledger-detail-actions">
      <AppButton v-if="documentError" :disabled="connectionLost || documentLoading" @click="store.loadLedgerDocument()">重新读取单据</AppButton>
      <AppButton @click="store.closeLedgerDocument()">关闭</AppButton>
    </div></template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 资料列随窗口收缩，长名称与规格完整换行；表格沿用公共横向滚动和分页。 */
.ledger-material-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px 28px; margin: 16px 0; }
.ledger-material-facts dt { color: var(--workspace-field-muted); font-size: 12px; margin-bottom: 7px; }
.ledger-material-facts dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.ledger-scope { color: var(--workspace-field-muted); line-height: 1.7; }
.ledger-scope small { display: block; }
.ledger-time { white-space: nowrap; font-variant-numeric: tabular-nums; }
.ledger-detail-actions { display: flex; justify-content: flex-end; gap: 10px; margin-left: auto; }
.ledger-detail-error { color: var(--app-danger, #b94438); }
.ledger-balances p { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 8px 0; }
@media (max-width: 760px) { .ledger-material-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .ledger-material-facts { grid-template-columns: 1fr; } }
</style>
