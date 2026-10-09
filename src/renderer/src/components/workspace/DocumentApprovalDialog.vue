<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceDocumentDialog from './WorkspaceDocumentDialog.vue'
import { documentApprovalLayout } from '../../utils/document-approval-layout'
import { usePiniaAppStore } from '../../store/app-store'
import DocumentApprovalPanel from './DocumentApprovalPanel.vue'
import OtherInboundReopenTrace from './OtherInboundReopenTrace.vue'

// 审批复用查看详情的公共单据布局，业务内容始终来自服务端送审快照。
withDefaults(defineProps<{ title?: string }>(), { title: '单据审批' })
const store = usePiniaAppStore()
const { documentApprovalTarget: target, documentApprovalRecord: record, busy, documentApprovalLoading: loading, connectionLost } = storeToRefs(store)
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const layout = computed(() => documentApprovalLayout(record.value))
const columns = [{ key: 'label', title: '物料编码 / 名称', width: '440' },
  { key: 'value', title: '数量 / 单位', width: '140' }]
</script>

<template>
  <!-- 未打开时不读取审批摘要，保持页面进入时审批内容按需加载的原行为。 -->
  <WorkspaceDocumentDialog :show="!!target" read-only :busy="busy" class="document-approval-dialog"
    :data="target ? layout.lines : []" :columns="columns" :show-lines="!!target && layout.showLines" :min-table-width="580"
    :title="`${title}${target?.intent === 'reverse' ? (['OpeningBalance', 'SubledgerOpening'].includes(target.document_type) ? ' · 撤销审批' : ' · 冲销审批') : ''}${record?.document_no ? ` · ${record.document_no}` : ''}`"
    @update:show="value => { if (!value) store.closeDocumentApproval() }">
    <template #beforeBasicInfo>
      <!-- 进度优先展示，单据正文与历史仍使用同一服务端快照。 -->
      <DocumentApprovalPanel part="progress" />
      <!-- 重开是独立业务事件，不伪装为原单审批步骤；两端可查看各自真实审批。 -->
      <OtherInboundReopenTrace v-if="record?.reopen_trace?.length" :links="record.reopen_trace"
        :current-id="record.document_id" :local-time="store.localTime" :disabled="disabled"
        @open="id => store.openDocumentApproval({ document_type: 'WarehouseInbound', document_id: id, intent: 'execute' })" />
      <slot />
    </template>
    <template #basicInfo>
      <div v-for="(item, index) in layout.basic" :key="index" class="document-detail-field">
        <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
      </div>
    </template>
    <template #cell-label="{ row }"><strong class="approval-value">{{ row.label }}</strong></template>
    <template #cell-value="{ row }"><span class="approval-value">{{ row.value }}</span></template>
    <template #afterLines>
      <DocumentApprovalPanel part="opinion" />
    </template>
    <template #footer>
      <DocumentApprovalPanel part="actions" />
    </template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 审批正文保留服务端快照的换行和长文本，操作控件与详情共享。 */
.approval-value { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
