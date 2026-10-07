<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { DocumentApprovalType } from '../../../../shared/document-approval-api'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import { usePiniaAppStore } from '../../store/app-store'

// 只负责表单交互，模板读取、版本、保存与草稿全部由 Pinia 持有。
const store = usePiniaAppStore()
const { user, busy, connectionLost, roles, approvalPolicies: policies, approvalPolicyDrafts: drafts,
  approvalPolicyLoading: loading, approvalPolicyError: error } = storeToRefs(store)
const { loadApprovalPolicies, editApprovalPolicy, saveApprovalPolicy } = store
const selected = ref<DocumentApprovalType>('WarehouseInbound')
const administrator = computed(() => user.value?.roles.includes('admin') ?? false)
const draft = computed(() => drafts.value[selected.value])
const saved = computed(() => policies.value.find(row => row.document_type === selected.value))
const disabled = computed(() => busy.value || loading.value || connectionLost.value || !administrator.value)
const typeOptions = computed(() => policies.value.map(row => ({ value: row.document_type, label: row.title })))
const roleOptions = computed(() => [{ value: '', label: '不限职务（仍须有该单据审核权限）' },
  ...roles.value.map(role => ({ value: role.code, label: role.label }))])

async function reload(): Promise<void> {
  if (await loadApprovalPolicies()) editApprovalPolicy(selected.value)
}
function choose(): void { editApprovalPolicy(selected.value) }
function addStep(): void {
  if (!disabled.value && draft.value && draft.value.steps.length < 5) draft.value.steps.push({ name: '批准', role: null })
}
function removeStep(index: number): void {
  if (!disabled.value && draft.value && draft.value.steps.length > 1) draft.value.steps.splice(index, 1)
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
    <p class="muted">默认由一位独立人员批准，可按单据增加审核、核准和批准步骤。建单、编辑及提交人员不能审批本单，各步骤由不同人员完成。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="stack" @submit.prevent="saveApprovalPolicy(selected)">
      <label>单据类型<WorkspaceSelect v-model="selected" :options="typeOptions" :disabled="disabled" @change="choose" /></label>
      <div v-if="draft" class="approval-steps">
        <div v-for="(step, index) in draft.steps" :key="index" class="approval-step">
          <span class="pill">{{ index + 1 }}</span>
          <label>步骤名称<AppInput v-model="step.name" required maxlength="40" :disabled="disabled" /></label>
          <label>审批职务<WorkspaceSelect :model-value="step.role ?? ''" :options="roleOptions" :disabled="disabled"
            @update:model-value="step.role = $event || null" /></label>
          <AppButton :disabled="disabled || draft.steps.length === 1" @click="removeStep(index)">移除</AppButton>
        </div>
        <div class="approval-actions">
          <AppButton :disabled="disabled || draft.steps.length >= 5" @click="addStep">增加步骤</AppButton>
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
/* 步骤顺序保持一致，窄窗口按行折叠，不挤压职务下拉与操作按钮。 */
.approval-settings label { display: grid; gap: 8px; min-width: 0; }
.approval-steps { display: grid; gap: 16px; }
.approval-step { display: grid; grid-template-columns: auto minmax(140px, 1fr) minmax(220px, 1.5fr) auto; gap: 12px; align-items: end; }
.approval-step > .pill { align-self: center; }
.approval-actions { display: flex; flex-wrap: wrap; gap: 12px; }
@media (max-width: 850px) { .approval-step { grid-template-columns: auto minmax(0, 1fr); } .approval-step > label:nth-of-type(2) { grid-column: 2; } .approval-step > :last-child { grid-column: 2; justify-self: start; } }
</style>
