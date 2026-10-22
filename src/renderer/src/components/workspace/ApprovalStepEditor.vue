<script setup lang="ts">
import { documentApprovalStepAction, documentApprovalStepLabels, type DocumentApprovalStep,
  type DocumentApprovalStepAction } from '../../../../shared/document-approval-api'
import AppButton from '../app/AppButton.vue'
import AppInput from '../app/AppInput.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'

const props = defineProps<{ steps: DocumentApprovalStep[]; disabled: boolean }>()
const emit = defineEmits<{ 'update:steps': [steps: DocumentApprovalStep[]] }>()
const actionOptions = Object.entries(documentApprovalStepLabels).map(([value, label]) => ({ value, label }))
function changeAction(index: number, value: string): void {
  if (props.disabled || !actionOptions.some(option => option.value === value)) return
  const step = props.steps[index]
  if (!step) return
  const oldLabel = documentApprovalStepLabels[documentApprovalStepAction(step)]
  step.action = value as DocumentApprovalStepAction
  if (step.name === oldLabel) step.name = documentApprovalStepLabels[step.action]
  step.role = null
}
function add(): void {
  if (!props.disabled && props.steps.length < 5) emit('update:steps', [...props.steps, { name: '批准', role: null, action: 'approve' }])
}
function remove(index: number): void {
  if (!props.disabled && props.steps.length > 1) emit('update:steps', props.steps.filter((_, at) => at !== index))
}
</script>

<template>
  <div class="approval-steps">
    <div v-for="(step, index) in steps" :key="index" class="approval-step">
      <span class="pill">{{ index + 1 }}</span>
      <label>步骤名称<AppInput v-model="step.name" required maxlength="40" :disabled="disabled" /></label>
      <label>审批操作<WorkspaceSelect :model-value="documentApprovalStepAction(step)" :options="actionOptions" :disabled="disabled"
        @update:model-value="changeAction(index, $event)" /></label>
      <AppButton :disabled="disabled || steps.length === 1" @click="remove(index)">移除</AppButton>
    </div>
    <AppButton class="add-step" :disabled="disabled || steps.length >= 5" @click="add">增加步骤</AppButton>
  </div>
</template>

<style scoped>
/* 默认流程与金额分支共用相同的步骤编辑器，窄窗口保持原有折行方式。 */
label { display: grid; gap: 8px; min-width: 0; }
.approval-steps { display: grid; gap: 16px; }
.approval-step { display: grid; grid-template-columns: auto minmax(140px, 1fr) minmax(180px, 1.5fr) auto; gap: 12px; align-items: end; }
.approval-step > .pill { align-self: center; }
.add-step { justify-self: start; }
@media (max-width: 850px) { .approval-step { grid-template-columns: auto minmax(0, 1fr); } .approval-step > label:nth-of-type(2) { grid-column: 2; } .approval-step > :last-child { grid-column: 2; justify-self: start; } }
</style>
