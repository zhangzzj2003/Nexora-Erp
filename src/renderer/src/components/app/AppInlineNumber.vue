<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import AppButton from './AppButton.vue'
import AppInput from './AppInput.vue'

// 默认展示数字，点击或键盘激活后编辑；原生输入常驻以保留表单必填与范围校验。
const props = withDefaults(defineProps<{
  modelValue: string
  label: string
  disabled?: boolean
  required?: boolean
  min?: string
  max?: string
  step?: string
}>(), { disabled: false, required: false, min: '0', step: '0.01' })
const emit = defineEmits<{
  'update:modelValue': [value: string]
  editStart: []
  editCancel: []
}>()
const root = ref<HTMLElement | null>(null)
const editing = ref(false)
let originalValue = ''
function input(): HTMLInputElement | null { return root.value?.querySelector('input') ?? null }
async function startEdit(): Promise<void> {
  if (props.disabled || editing.value) return
  originalValue = props.modelValue
  emit('editStart')
  editing.value = true
  await nextTick()
  input()?.focus()
  input()?.select()
}
function update(value: string): void {
  if (!props.disabled) emit('update:modelValue', value)
}
async function finishEdit(focusDisplay = false): Promise<void> {
  editing.value = false
  if (focusDisplay) {
    await nextTick()
    root.value?.querySelector('button')?.focus()
  }
}
function keydown(event: KeyboardEvent): void {
  // 文本按钮的 Enter/空格由原生按钮负责激活，只有编辑态才接管快捷键。
  if (!editing.value) return
  if (event.key === 'Enter') {
    // Enter 只结束当前单元格，不意外提交整张采购单。
    event.preventDefault()
    if (input()?.reportValidity()) void finishEdit(true)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    update(originalValue)
    emit('editCancel')
    void finishEdit(true)
  }
}
function invalid(event: Event): void {
  if (editing.value || props.disabled) return
  // 隐藏输入校验失败时先显露并聚焦，避免浏览器无法定位必填项。
  event.preventDefault()
  void startEdit().then(() => input()?.reportValidity())
}
watch(() => props.disabled, disabled => { if (disabled) editing.value = false })
</script>
<template>
  <div ref="root" class="app-inline-number" @invalid.capture="invalid" @keydown="keydown">
    <AppButton v-if="!editing" variant="plain" class="app-inline-number__display" :disabled="disabled"
      :aria-label="`${label}，${modelValue || '未填写'}，点击编辑`" :title="`${label}：${modelValue || '点击填写'}`"
      @click="startEdit">{{ modelValue || '点击填写' }}</AppButton>
    <AppInput v-show="editing" :model-value="modelValue" :disabled="disabled" :required="required"
      :aria-label="label" type="number" :min="min" :max="max" :step="step" hide-number-controls
      @update:model-value="update" @blur="finishEdit()" />
  </div>
</template>
<style scoped>
/* 文本态保留完整单元格点击面积，金额靠右；只有编辑时显示输入框边界。 */
.app-inline-number { min-width: 0; width: 100%; }
.app-inline-number__display { min-height: 40px; width: 100%; padding: 0 10px; text-align: right; justify-content: flex-end; font-variant-numeric: tabular-nums; }
.app-inline-number__display :deep(.n-button__content) { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-inline-number__display:focus-visible { outline: 2px solid var(--workspace-field-accent); outline-offset: 2px; border-radius: 8px; }
</style>
