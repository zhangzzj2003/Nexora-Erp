<script setup lang="ts">
import { computed } from 'vue'
import { documentApprovalStepAction, documentApprovalStepLabels } from '../../../../shared/document-approval-api'
import { storeToRefs } from 'pinia'
import WorkspaceDocumentDialog from './WorkspaceDocumentDialog.vue'
import { documentApprovalLayout } from '../../utils/document-approval-layout'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import { usePiniaAppStore } from '../../store/app-store'
import DocumentApprovalProgress from './DocumentApprovalProgress.vue'
import OtherInboundReopenTrace from './OtherInboundReopenTrace.vue'
import { approvalTargetKey } from '../../store/modules/document-approval-case-actions'

// 审批复用查看详情的公共单据布局，业务内容始终来自服务端送审快照。
withDefaults(defineProps<{ title?: string }>(), { title: '单据审批' })
const store = usePiniaAppStore()
const { documentApprovalTarget: target, documentApprovalRecord: record,
  documentApprovalLoading: loading, documentApprovalError: error,
  documentApprovalReasons: reasons, documentApprovalEvidence: evidence, busy, connectionLost } = storeToRefs(store)
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const key = computed(() => target.value ? approvalTargetKey(target.value) : '')
const layout = computed(() => documentApprovalLayout(record.value))
// 保留服务端物料名称及数量单位，不拆解显示文本或重新计算审批内容。
const columns = [{ key: 'label', title: '物料编码 / 名称', width: '440' },
  { key: 'value', title: '数量 / 单位', width: '140' }]
// 按钮名称与授权动作一致；自定义步骤名称仍由顶部流程展示。
const reviewLabel = computed(() => {
  const step = record.value?.steps[record.value.current_step]
  return step ? documentApprovalStepLabels[documentApprovalStepAction(step)] : '批准'
})
// 报价、售后及处置保留原必填依据，售后与处置意见最多二百字。
const quoteReasonRequired = computed(() => ['ControlBalanceTransfer', 'CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ProductionCostSettlement'].includes(target.value?.document_type ?? ''))
const maintenance = computed(() => target.value?.document_type === 'MaintenanceJob')
const evidenceMissing = computed(() => maintenance.value && !evidence.value[key.value]?.trim())
const reversalSubmit = computed(() => target.value?.intent === 'reverse' && record.value?.can_submit)
</script>

<template>
  <!-- 未打开时不读取审批摘要，保持页面进入时审批内容按需加载的原行为。 -->
  <WorkspaceDocumentDialog :show="!!target" read-only :busy="busy" class="document-approval-dialog"
    :data="target ? layout.lines : []" :columns="columns" :show-lines="!!target && layout.showLines" :min-table-width="580"
    :title="`${title}${target?.intent === 'reverse' ? (['OpeningBalance', 'SubledgerOpening'].includes(target.document_type) ? ' · 撤销审批' : ' · 冲销审批') : ''}${record?.document_no ? ` · ${record.document_no}` : ''}`"
    @update:show="value => { if (!value) store.closeDocumentApproval() }">
    <template #beforeBasicInfo>
      <!-- 进度优先展示，单据正文与历史仍使用同一服务端快照。 -->
      <DocumentApprovalProgress v-if="record" :record="record" :roles="store.roles" :local-time="store.localTime" />
      <!-- 重开是独立业务事件，不伪装为原单审批步骤；两端可查看各自真实审批。 -->
      <OtherInboundReopenTrace v-if="record?.reopen_trace?.length" :links="record.reopen_trace"
        :current-id="record.document_id" :local-time="store.localTime" :disabled="disabled"
        @open="id => store.openDocumentApproval({ document_type: 'WarehouseInbound', document_id: id, intent: 'execute' })" />
      <slot />
      <p v-if="loading" role="status">正在读取审批记录…</p>
      <p v-if="error" role="alert" class="approval-error">{{ error }}</p>
      <template v-if="record">
        <!-- 已执行单据的后续合同证据保留原快照，不要求撤回已经执行的审批。 -->
        <p v-if="!record.content_matches && record.status !== 'executed'" role="alert" class="approval-error">当前单据内容与送审内容不一致，请撤回后重新送审。</p>
        <p v-else-if="!record.content_matches" class="approval-hint">当前正文与执行时审批快照不同，下方保留原审批内容，请核对后续变更记录。</p>
      </template>
    </template>
    <template #basicInfo>
      <div v-for="(item, index) in layout.basic" :key="index" class="document-detail-field">
        <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
      </div>
    </template>
    <template #cell-label="{ row }"><strong class="approval-value">{{ row.label }}</strong></template>
    <template #cell-value="{ row }"><span class="approval-value">{{ row.value }}</span></template>
    <template #afterLines>
      <section v-if="record" class="approval-content" aria-label="审批意见">
        <!-- 完工的质检前置由服务端约束；这里说明不能送审的实际原因。 -->
        <p v-if="record.document_type === 'ProductionCompletion' && record.intent === 'execute' && record.business_status === 'draft'">请先记录质检结果，完成后再提交本单审批。</p>
        <p v-if="record.reversal_evidence">送审验收更正依据：{{ record.reversal_evidence }}</p>
        <p v-if="record.reversal_reason">送审{{ ['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销' : '冲销' }}原因：{{ record.reversal_reason }}</p>
        <label v-if="reversalSubmit || record.can_review || (quoteReasonRequired && record.can_submit)" class="approval-reason">
          {{ reversalSubmit ? (['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销原因（必填）' : '冲销原因（必填）') : quoteReasonRequired ? `${record.document_type === 'AfterSalesCase' ? '售后' : record.document_type === 'QualityDisposition' ? '处置' : record.document_type === 'MrpPlan' ? '计划' : record.document_type === 'MaintenanceJob' ? '维护' : record.document_type === 'ControlBalanceTransfer' ? '转账' : record.document_type === 'Journal' ? '凭证' : record.document_type === 'OpeningBalance' ? '期初' : record.document_type === 'SubledgerOpening' ? '分户' : record.document_type === 'ProductionCostSettlement' ? '结算' : ['SubledgerSettlement', 'SubledgerOrderSettlement'].includes(record.document_type) ? '核销' : ['PaymentRecord','SubledgerPayment','OrderSettlementTransfer'].includes(record.document_type) ? '资金' : '报价'}操作依据（必填）` : '审批意见（驳回时必填）' }}
          <AppInput v-model="reasons[key]" :maxlength="reversalSubmit || ['ControlBalanceTransfer', 'AfterSalesCase', 'QualityDisposition', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ProductionCostSettlement'].includes(record.document_type) ? 200 : 500" :disabled="disabled" />
        </label>
        <!-- 现场依据保持原维护领域的独立字段，审核意见不覆盖更正执行依据。 -->
        <label v-if="maintenance && (record.can_submit || record.can_review)" class="approval-reason">现场依据（必填）
          <AppInput v-model="evidence[key]" maxlength="600" :disabled="disabled" />
        </label>
      </section>
    </template>
    <template #footer>
      <div class="approval-footer">
        <AppButton type="button" :disabled="disabled" @click="store.loadDocumentApproval()">刷新记录</AppButton>
        <AppButton v-if="record?.can_withdraw" type="button" :disabled="disabled"
          @click="store.actDocumentApproval('withdraw')">撤回审批</AppButton>
        <AppButton v-if="record?.can_submit" type="button" variant="primary"
          :disabled="disabled || evidenceMissing || ((reversalSubmit || quoteReasonRequired) && !reasons[key]?.trim())"
          @click="store.actDocumentApproval('submit')">提交审批</AppButton>
        <AppButton v-if="record?.can_review" type="button" :disabled="disabled || evidenceMissing || !reasons[key]?.trim()"
          @click="store.actDocumentApproval('reject')">驳回</AppButton>
        <AppButton v-if="record?.can_review" type="button" variant="primary" :disabled="disabled || evidenceMissing || (quoteReasonRequired && !reasons[key]?.trim())"
          @click="store.actDocumentApproval('approve')">{{ reviewLabel }}</AppButton>
      </div>
    </template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 节点记录与顶部流程联动，正文下方只保留意见输入，页脚仍由公共组件固定。 */
.approval-content { margin-top: 24px; overflow-wrap: anywhere; }
.approval-value { white-space: pre-wrap; overflow-wrap: anywhere; }
.approval-hint { color: var(--workspace-field-muted); line-height: 1.7; }
.approval-error { color: #b94438; }
:root[data-theme='dark'] .approval-error { color: #ffaaa2; }
.approval-reason { display: grid; gap: 8px; }
.approval-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; width: 100%; }
</style>
