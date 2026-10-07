<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { accountRoleText } from '../../utils/account-role'
import { approvalTargetKey } from '../../store/modules/document-approval-case-actions'

// 单据页面提供业务摘要，通用弹窗只负责审批步骤、意见与完整操作记录。
withDefaults(defineProps<{ title?: string }>(), { title: '单据审批' })
const store = usePiniaAppStore()
const { documentApprovalTarget: target, documentApprovalRecord: record,
  documentApprovalLoading: loading, documentApprovalError: error,
  documentApprovalReasons: reasons, documentApprovalEvidence: evidence, busy, connectionLost } = storeToRefs(store)
const disabled = computed(() => busy.value || loading.value || connectionLost.value)
const key = computed(() => target.value ? approvalTargetKey(target.value) : '')
const labels = { draft: '未送审', submitted: '审批中', approved: '已批准，待执行', rejected: '已驳回', withdrawn: '已撤回', executed: '已执行' }
const actions = { submit: '送审', approve: '批准', reject: '驳回', withdraw: '撤回', execute: '执行' }
// 报价、售后及处置保留原必填依据，售后与处置意见最多二百字。
const quoteReasonRequired = computed(() => ['CrmQuote', 'AfterSalesCase', 'QualityDisposition', 'MrpPlan', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'ProductionCostSettlement'].includes(target.value?.document_type ?? ''))
const maintenance = computed(() => target.value?.document_type === 'MaintenanceJob')
const evidenceMissing = computed(() => maintenance.value && !evidence.value[key.value]?.trim())
const reversalSubmit = computed(() => target.value?.intent === 'reverse' && record.value?.can_submit)
</script>

<template>
  <NModal :show="!!target" preset="card" class="document-approval-dialog"
    :title="`${title}${target?.intent === 'reverse' ? (['OpeningBalance', 'SubledgerOpening'].includes(target.document_type) ? ' · 撤销审批' : ' · 冲销审批') : ''}${record?.document_no ? ` · ${record.document_no}` : ''}`"
    :style="{ width: 'min(760px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 48px)' }"
    :mask-closable="!busy" :close-on-esc="!busy" :closable="!busy"
    @update:show="value => { if (!value) store.closeDocumentApproval() }">
    <div class="approval-content">
      <slot />
      <p v-if="loading" role="status">正在读取审批记录…</p>
      <p v-if="error" role="alert" class="approval-error">{{ error }}</p>
      <template v-if="record">
        <!-- 已执行单据的后续合同证据保留原快照，不要求撤回已经执行的审批。 -->
        <p v-if="!record.content_matches && record.status !== 'executed'" role="alert" class="approval-error">当前单据内容与送审内容不一致，请撤回后重新送审。</p>
        <p v-else-if="!record.content_matches" class="approval-hint">当前正文与执行时审批快照不同，下方保留原审批内容，请核对后续变更记录。</p>
        <dl class="approval-summary">
          <div v-for="(item, index) in record.summary" :key="index"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div>
        </dl>
        <!-- 已下达或已完工的历史工单同样保留原流程，不能误显示为等待新审批。 -->
        <p v-if="record.intent === 'execute' && record.version === 0 && ['posted', 'cancelled', 'confirmed', 'partially_shipped', 'shipped', 'closed', 'released', 'in_progress', 'completed', 'converted', 'processing', 'received', 'repaired', 'reversed', 'accepted', 'reported'].includes(record.business_status)">已处理单据保留原业务记录，不补造审批记录。</p>
        <!-- 旧申请全部转完后只保留原事实；剩余需求的新批准不能倒写成历史订单的批准。 -->
        <p v-else-if="record.document_type === 'PurchaseRequest' && record.version === 0 && record.business_status === 'approved' && !record.can_submit">申请已无待转数量，保留原转单记录，不补造审批。</p>
        <p v-else><strong>{{ labels[record.status] }}</strong> · 审批版本 {{ record.version }}</p>
        <!-- 完工的质检前置由服务端约束；这里说明不能送审的实际原因。 -->
        <p v-if="record.document_type === 'ProductionCompletion' && record.intent === 'execute' && record.business_status === 'draft'">请先记录质检结果，完成后再提交本单审批。</p>
        <p class="approval-hint">建单、编辑、提交人员不能自审；不同审批步骤由不同人员完成。批准后仍需执行对应业务操作。</p>
        <ol v-if="record.steps.length" class="approval-steps">
          <li v-for="(step, index) in record.steps" :key="index"
            :class="{ completed: index < record.current_step, current: record.status === 'submitted' && index === record.current_step }">
            <strong>{{ index + 1 }}. {{ step.name }}</strong><span>{{ step.role ? `指定角色：${accountRoleText([step.role], store.roles)}` : '由有审核权限的人员处理' }}</span>
          </li>
        </ol>
        <p v-if="record.reversal_evidence">送审验收更正依据：{{ record.reversal_evidence }}</p>
        <p v-if="record.reversal_reason">送审{{ ['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销' : '冲销' }}原因：{{ record.reversal_reason }}</p>
        <label v-if="reversalSubmit || record.can_review || (quoteReasonRequired && record.can_submit)" class="approval-reason">
          {{ reversalSubmit ? (['OpeningBalance', 'SubledgerOpening'].includes(record.document_type) ? '撤销原因（必填）' : '冲销原因（必填）') : quoteReasonRequired ? `${record.document_type === 'AfterSalesCase' ? '售后' : record.document_type === 'QualityDisposition' ? '处置' : record.document_type === 'MrpPlan' ? '计划' : record.document_type === 'MaintenanceJob' ? '维护' : record.document_type === 'Journal' ? '凭证' : record.document_type === 'OpeningBalance' ? '期初' : record.document_type === 'SubledgerOpening' ? '分户' : record.document_type === 'ProductionCostSettlement' ? '结算' : ['PaymentRecord','SubledgerPayment','OrderSettlementTransfer'].includes(record.document_type) ? '资金' : '报价'}操作依据（必填）` : '审批意见（驳回时必填）' }}
          <AppInput v-model="reasons[key]" :maxlength="reversalSubmit || ['AfterSalesCase', 'QualityDisposition', 'MaintenanceJob', 'Journal', 'OpeningBalance', 'SubledgerOpening', 'PaymentRecord', 'SubledgerPayment', 'OrderSettlementTransfer', 'ProductionCostSettlement'].includes(record.document_type) ? 200 : 500" :disabled="disabled" />
        </label>
        <!-- 现场依据保持原维护领域的独立字段，审核意见不覆盖更正执行依据。 -->
        <label v-if="maintenance && (record.can_submit || record.can_review)" class="approval-reason">现场依据（必填）
          <AppInput v-model="evidence[key]" maxlength="600" :disabled="disabled" />
        </label>
        <h3>审批记录</h3>
        <p v-if="!record.events.length" class="approval-hint">尚无审批记录。</p>
        <ol class="approval-history">
          <li v-for="event in record.events" :key="event.id">
            <strong>{{ event.action === 'approve' ? event.step_name || '批准' : actions[event.action] }} · {{ event.actor_name }}</strong>
            <small>{{ store.localTime(event.created_at) }} · 第 {{ event.generation }} 次送审</small>
            <p v-if="event.reason">{{ event.reason }}</p><p v-if="event.evidence">现场依据：{{ event.evidence }}</p>
          </li>
        </ol>
      </template>
    </div>
    <footer class="approval-footer">
      <AppButton type="button" :disabled="disabled" @click="store.loadDocumentApproval()">刷新记录</AppButton>
      <AppButton v-if="record?.can_withdraw" type="button" :disabled="disabled"
        @click="store.actDocumentApproval('withdraw')">撤回审批</AppButton>
      <AppButton v-if="record?.can_submit" type="button" variant="primary"
        :disabled="disabled || evidenceMissing || ((reversalSubmit || quoteReasonRequired) && !reasons[key]?.trim())"
        @click="store.actDocumentApproval('submit')">提交审批</AppButton>
      <AppButton v-if="record?.can_review" type="button" :disabled="disabled || evidenceMissing || !reasons[key]?.trim()"
        @click="store.actDocumentApproval('reject')">驳回</AppButton>
      <AppButton v-if="record?.can_review" type="button" variant="primary" :disabled="disabled || evidenceMissing || (quoteReasonRequired && !reasons[key]?.trim())"
        @click="store.actDocumentApproval('approve')">{{ record.steps[record.current_step]?.name || '批准' }}</AppButton>
    </footer>
  </NModal>
</template>

<style scoped>
/* 明细可滚动，审批操作固定在页脚，窄窗口仍能看到失败原因和按钮。 */
.approval-content { max-height: calc(100dvh - 240px); overflow-y: auto; overflow-wrap: anywhere; }
.approval-hint { color: var(--workspace-field-muted); line-height: 1.7; }
.approval-error { color: #b94438; }
:root[data-theme='dark'] .approval-error { color: #ffaaa2; }
.approval-steps, .approval-history { list-style: none; padding: 0; display: grid; gap: 10px; }
.approval-steps li { padding: 12px 16px; border: 1px solid var(--workspace-field-border); border-radius: 10px; display: grid; gap: 6px; }
.approval-steps .current { border-color: var(--workspace-field-accent); }
.approval-steps .completed { opacity: .75; }
.approval-steps span, .approval-history small { display: block; color: var(--workspace-field-muted); font-size: 12px; }
.approval-summary { display: grid; gap: 8px; margin: 0 0 18px; }
.approval-summary div { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(120px, 2fr); gap: 12px; }
.approval-summary dt { color: var(--workspace-field-muted); }
.approval-summary dd { margin: 0; white-space: pre-wrap; }
.approval-reason { display: grid; gap: 8px; }
.approval-history li { padding: 10px 0; border-bottom: 1px solid var(--workspace-field-border); }
.approval-history p { margin: 6px 0 0; white-space: pre-wrap; }
.approval-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; padding-top: 18px; margin-top: 18px; border-top: 1px solid var(--workspace-field-border); }
</style>
