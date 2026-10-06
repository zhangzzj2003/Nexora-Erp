<script setup lang="ts" generic="T extends WorkspaceSelectValue">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NSelect } from 'naive-ui'
import type { SelectInst } from 'naive-ui'
import { useThemeStore } from '../../store/theme-store'
import {
  hasWorkspaceSelection,
  resolveWorkspaceSelection,
  workspaceSelectKey,
  workspaceSelectTheme
} from '../../utils/workspace-select'
import type { WorkspaceSelectOption, WorkspaceSelectValue } from '../../utils/workspace-select'

// 页面只传原始业务值与选项；搜索、键盘操作、菜单定位和关闭行为交给 Naive UI。
defineOptions({ inheritAttrs: false })
const props = withDefaults(
  defineProps<{
    modelValue: T
    options: readonly WorkspaceSelectOption<T>[]
    disabled?: boolean
    required?: boolean
    filterable?: boolean
    placeholder?: string
    size?: 'small' | 'medium'
    ariaLabel?: string
    // 富信息选项需要固定的两行高度，普通下拉保持原有尺寸和虚拟滚动。
    optionHeight?: number
  }>(),
  { disabled: false, required: false, filterable: true, placeholder: '请选择', size: 'medium' }
)
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const select = ref<SelectInst | null>(null)
const invalid = ref(false)
const { isDarkTheme, colorPalette } = storeToRefs(useThemeStore())
const theme = computed(() => {
  const result = workspaceSelectTheme(isDarkTheme.value, colorPalette.value)
  const menu = result.peers?.InternalSelectMenu
  if (menu && props.optionHeight) {
    menu.optionHeightMedium = `${props.optionHeight}px`
    menu.optionHeightSmall = `${props.optionHeight}px`
  }
  return result
})
const menuOptions = computed(() =>
  props.options.map((option) => ({ ...option, value: workspaceSelectKey(option.value) }))
)
const valid = computed(() => hasWorkspaceSelection(props.options, props.modelValue))
function update(key: unknown): void {
  const option = resolveWorkspaceSelection(props.options, key, props.disabled)
  if (!option) return
  invalid.value = false
  // 先同步 v-model 再通知联动操作，订单切换等回调才能读到新的编号。
  emit('update:modelValue', option.value)
  emit('change', option.value)
}
function focusInvalid(): void {
  invalid.value = true
  select.value?.focus()
}
defineExpose({ focus: () => select.value?.focus() })
</script>

<template>
  <span class="workspace-select" :class="{ 'workspace-select--small': size === 'small' }">
    <NSelect
      ref="select"
      to="body"
      v-bind="$attrs"
      :value="workspaceSelectKey(modelValue)"
      :options="menuOptions"
      :disabled="disabled"
      :filterable="filterable"
      :placeholder="placeholder"
      :size="size"
      :theme-overrides="theme"
      :fallback-option="false"
      :status="invalid && !valid ? 'error' : undefined"
      :input-props="{
        'aria-label': ariaLabel,
        'aria-required': required,
        'aria-invalid': invalid && !valid
      }"
      @update:value="update"
    >
      <template #empty>暂无可选项</template>
    </NSelect>
    <!-- Naive UI 的选择框不是原生表单元素；校验代理保留 required，禁用时不阻止提交。 -->
    <input
      v-if="required"
      class="workspace-select__validation"
      :value="valid ? 'selected' : ''"
      :disabled="disabled"
      required
      tabindex="-1"
      aria-hidden="true"
      @invalid.prevent="focusInvalid"
      @focus="select?.focus()"
    />
  </span>
</template>

<style scoped>
/* 触发框占满所在表单列，菜单由 Naive UI 传送到 body，避免被表格或弹窗滚动区截断。 */
.workspace-select {
  display: block;
  position: relative;
  width: 100%;
  min-width: 0;
  font-weight: 400;
}
.workspace-select :deep(.n-base-selection-overlay__wrapper) {
  font-weight: 400;
}
.workspace-select :deep(input.n-base-selection-input) {
  min-height: 0;
  border: 0;
  border-radius: 0;
  padding: 0;
  background: transparent;
  outline: none;
  box-shadow: none;
}
/* 校验代理不可见但参与浏览器表单校验，焦点会转移到可操作的选择框。 */
.workspace-select__validation {
  position: absolute;
  top: 0;
  left: 0;
  width: 1px;
  height: 1px;
  min-height: 0;
  padding: 0;
  border: 0;
  opacity: 0;
  pointer-events: none;
}
</style>
