<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { amountApprovalTypes, type DocumentApprovalType } from '../../../../shared/document-approval-api'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import ApprovalStepEditor from './ApprovalStepEditor.vue'
import { usePiniaAppStore } from '../../store/app-store'

// 只负责表单交互，模板读取、版本、保存与草稿全部由 Pinia 持有。
const store = usePiniaAppStore()
const { user, busy, connectionLost, approvalPolicies: policies, approvalPolicyDrafts: drafts,
  approvalPolicyLoading: loading, approvalPolicyError: error } = storeToRefs(store)
const { loadApprovalPolicies, editApprovalPolicy, saveApprovalPolicy } = store
const selected = ref<DocumentApprovalType>('WarehouseInbound')
const administrator = computed(() => user.value?.roles.includes('admin') ?? false)
const draft = computed(() => drafts.value[selected.value])
const saved = computed(() => policies.value.find(row => row.document_type === selected.value))
const disabled = computed(() => busy.value || loading.value || connectionLost.value || !administrator.value)
const typeOptions = computed(() => policies.value.map(row => ({ value: row.document_type, label: row.title })))
// 同实例断线会清空远端规则缓存，已建立的金额草稿仍需可见；旧服务端未提供 branches 时不开放配置。
const supportsAmount = computed(() => amountApprovalTypes.includes(selected.value)
  && (!!saved.value?.amount_basis || draft.value?.branches !== undefined))

async function reload(): Promise<void> {
  if (await loadApprovalPolicies()) editApprovalPolicy(selected.value)
}
function choose(): void { editApprovalPolicy(selected.value) }
function addBranch(): void {
  if (disabled.value || !supportsAmount.value || !draft.value) return
  draft.value.branches ??= []
  if (draft.value.branches.length < 5) draft.value.branches.push({ name: '', min_amount: '0.00', max_amount: null,
    steps: [{ name: '批准', role: null, action: 'approve' }] })
}
function removeBranch(index: number): void {
  if (!disabled.value) draft.value?.branches?.splice(index, 1)
}
watch(() => [selected.value, saved.value?.version, disabled.value], () => {
  // 恢复登录时应用仍在加载其他业务；等全局忙碌结束后再建立草稿。
  if (!disabled.value && !draft.value) editApprovalPolicy(selected.value)
}, { immediate: true })
onMounted(() => { if (administrator.value) void reload() })
</script>

<template>
  <section v-if="administrator" class="card approval-settings">
    <div class="section-heading">
      <h2>单据审批步骤</h2>
      <AppButton :disabled="busy || loading || connectionLost" :loading="loading" @click="reload">刷新规则</AppButton>
    </div>
    <p class="muted">在“职务与权限”中按单据分配审核、核准、批准按钮权限；登录账号拥有当前步骤权限即可操作，建单人员也可审批，同一人员可完成多个已授权步骤。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="stack" @submit.prevent="saveApprovalPolicy(selected)">
      <label>单据类型<WorkspaceSelect v-model="selected" :options="typeOptions" :disabled="disabled" @change="choose" /></label>
      <div v-if="draft" class="approval-steps">
        <h3>默认步骤</h3>
        <p class="muted">没有命中金额区间时使用以下步骤；冲销与撤销申请始终使用默认步骤。</p>
        <ApprovalStepEditor v-model:steps="draft.steps" :disabled="disabled" />
        <section v-if="supportsAmount" class="approval-branches" aria-label="金额条件分支">
          <h3>金额条件分支</h3>
          <p class="muted">按{{ saved?.amount_basis || '单据固定金额' }}（人民币）选择流程。下限包含，上限不包含；上限留空表示不设上限。区间不能重叠。</p>
          <p v-if="!draft.branches?.length" class="muted">尚未设置金额分支，所有单据使用默认步骤。</p>
          <fieldset v-for="(branch, index) in draft.branches" :key="index" class="approval-branch">
            <legend>金额分支 {{ index + 1 }}</legend>
            <div class="approval-range">
              <label>分支名称<AppInput v-model="branch.name" required maxlength="40" :disabled="disabled" /></label>
              <label>金额下限（包含）<AppInput v-model="branch.min_amount" required inputmode="decimal" :disabled="disabled" /></label>
              <label>金额上限（不包含）<AppInput :model-value="branch.max_amount" inputmode="decimal" placeholder="不设上限" :disabled="disabled"
                @update:model-value="branch.max_amount = $event?.trim() || null" /></label>
            </div>
            <ApprovalStepEditor v-model:steps="branch.steps" :disabled="disabled" />
            <AppButton :disabled="disabled" tone="warning" @click="removeBranch(index)">移除金额分支</AppButton>
          </fieldset>
          <AppButton :disabled="disabled || (draft.branches?.length ?? 0) >= 5" @click="addBranch">增加金额分支</AppButton>
        </section>
        <div class="approval-actions">
          <AppButton type="submit" variant="primary" :disabled="disabled">保存审批规则</AppButton>
        </div>
        <p class="muted">送审时固定规则和内容；修改规则只影响之后重新送审的单据。</p>
        <div v-if="saved && saved.version !== draft.version" class="approval-conflict">
          <p class="error">服务端规则已更新；当前输入仍保留，请核对后重新载入规则。</p>
          <AppButton :disabled="disabled" @click="editApprovalPolicy(selected, true)">载入最新规则</AppButton>
        </div>
      </div>
      <p v-else-if="!loading" class="muted">读取审批规则后可设置步骤。</p>
    </form>
  </section>
</template>

<style scoped>
/* 分支沿用现有表单与分隔线，不再套入重复卡片。 */
.approval-settings label { display: grid; gap: 8px; min-width: 0; }
.approval-steps { display: grid; gap: 16px; }
.approval-branches { display: grid; gap: 16px; }
.approval-branches > button, .approval-branch > button { justify-self: start; }
.approval-branch { display: grid; gap: 20px; min-width: 0; margin: 0; padding: 20px 0; border: 0; border-top: 1px solid var(--workspace-field-border); }
.approval-branch legend { padding: 0 8px 0 0; font-weight: 600; }
.approval-range { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.approval-actions { display: flex; flex-wrap: wrap; gap: 12px; }
@media (max-width: 850px) { .approval-range { grid-template-columns: minmax(0, 1fr); } }
</style>
