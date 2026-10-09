<script setup lang="ts">
import { computed } from 'vue'
import { documentApprovalStepAction, documentApprovalStepLabels } from '../../../../shared/document-approval-api'
import { storeToRefs } from 'pinia'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import { usePiniaAppStore } from '../../store/app-store'
import DocumentApprovalProgress from './DocumentApprovalProgress.vue'
import { approvalTargetKey } from '../../store/modules/document-approval-case-actions'

// 同一套审批控件可嵌入详情；分区插槽让操作继续留在公共弹窗的固定页脚。
defineProps<{ part: 'progress' | 'opinion' | 'actions'; executionHint?: string; liveDetails?: boolean }>()
const store = usePiniaAppStore()
const { documentApprovalTarget: target, documentApprovalRecord: record,
  documentApprovalLoading: loading, documentApprovalError: error,
  documentApprovalReasons: reasons, documentApprovalEvidence: evidence, busy, connectionLost } = storeToRefs(store)
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const key = computed(() => target.value ? approvalTargetKey(target.value) : '')
// 按钮名称与授权动作一致；自定义步骤名称仍由顶部流程展示。
const reviewLabel = computed(() => {
  const step = record.value?.steps[record.value.current_step]
  return step ? documentApprovalStepLabels[documentApprovalStepAction(step)] : '批准'
})
// 报价、售后及处置保留原必填依据，售后与处置意见最多二百字。
const quoteReasonRequired = computed(() => ['CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ProductionCostSettlement'].includes(target.value?.document_type ?? ''))
const maintenance = computed(() => target.value?.document_type === 'MaintenanceJob')
const evidenceMissing = computed(() => maintenance.value && !evidence.value[key.value]?.trim())
const reversalSubmit = computed(() => target.value?.intent === 'reverse' && record.value?.can_submit)
</script>

<template>
  <div v-if="part === 'progress'" class="approval-panel-progress">
      <DocumentApprovalProgress v-if="record" :record="record" :roles="store.roles" :local-time="store.localTime" :execution-hint="executionHint" />
      <p v-if="loading" role="status">正在读取审批记录…</p>
      <p v-if="error" role="alert" class="approval-error">{{ error }}</p>
      <template v-if="record">
        <!-- 已执行单据的后续合同证据保留原快照，不要求撤回已经执行的审批。 -->
        <p v-if="!record.content_matches && record.status !== 'executed'" role="alert" class="approval-error">当前单据内容与送审内容不一致，请撤回后重新送审。</p>
        <p v-else-if="!record.content_matches" class="approval-hint">{{ liveDetails ? '当前详情与执行时审批快照不同，请核对原送审内容和后续变更记录。' : '当前正文与执行时审批快照不同，下方保留原审批内容，请核对后续变更记录。' }}</p>
      </template>
      <!-- 内嵌详情展示最新业务快照，发生差异时另行保留原送审内容供核对。 -->
      <section v-if="liveDetails && record && !record.content_matches" class="approval-snapshot">
        <h4>原送审内容</h4>
        <dl><template v-for="(item, index) in record.summary" :key="index"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></template></dl>
      </section>
  </div>
  <template v-else-if="part === 'opinion'">
      <section v-if="record" class="approval-content" aria-label="审批意见">
        <!-- 完工的质检前置由服务端约束；这里说明不能送审的实际原因。 -->
        <p v-if="record.document_type === 'ProductionCompletion' && record.intent === 'execute' && record.business_status === 'draft'">请先记录质检结果，完成后再提交本单审批。</p>
        <p v-if="record.reversal_evidence">送审验收更正依据：{{ record.reversal_evidence }}</p>
        <p v-if="record.reversal_reason">送审{{ ['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销' : '冲销' }}原因：{{ record.reversal_reason }}</p>
        <label v-if="reversalSubmit || record.can_review || (quoteReasonRequired && record.can_submit)" class="approval-reason">
          {{ reversalSubmit ? (['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销原因（必填）' : '冲销原因（必填）') : quoteReasonRequired ? `${record.document_type === 'AfterSalesCase' ? '售后' : record.document_type === 'QualityDisposition' ? '处置' : record.document_type === 'MrpPlan' ? '计划' : record.document_type === 'MaintenanceJob' ? '维护' : record.document_type === 'Journal' ? '凭证' : record.document_type === 'OpeningBalance' ? '期初' : record.document_type === 'SubledgerOpening' ? '分户' : record.document_type === 'ProductionCostSettlement' ? '结算' : ['SubledgerSettlement', 'SubledgerOrderSettlement'].includes(record.document_type) ? '核销' : ['PaymentRecord','SubledgerPayment','OrderSettlementTransfer'].includes(record.document_type) ? '资金' : '报价'}操作依据（必填）` : '审批意见（驳回时必填）' }}
          <AppInput v-model="reasons[key]" :maxlength="reversalSubmit || ['AfterSalesCase', 'QualityDisposition', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'SubledgerSettlement', 'SubledgerOrderSettlement', 'ProductionCostSettlement'].includes(record.document_type) ? 200 : 500" :disabled="disabled" />
        </label>
        <!-- 现场依据保持原维护领域的独立字段，审核意见不覆盖更正执行依据。 -->
        <label v-if="maintenance && (record.can_submit || record.can_review)" class="approval-reason">现场依据（必填）
          <AppInput v-model="evidence[key]" maxlength="600" :disabled="disabled" />
        </label>
      </section>
  </template>
  <template v-else>
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
</template>

<style scoped>
/* 节点记录与顶部流程联动，正文下方只保留意见输入，页脚仍由公共组件固定。 */
.approval-snapshot { margin-bottom: 18px; white-space: pre-wrap; overflow-wrap: anywhere; }
.approval-content { margin-top: 24px; overflow-wrap: anywhere; }
.approval-hint { color: var(--workspace-field-muted); line-height: 1.7; }
.approval-error { color: #b94438; }
:root[data-theme='dark'] .approval-error { color: #ffaaa2; }
.approval-reason { display: grid; gap: 8px; }
.approval-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; width: 100%; }
</style>
