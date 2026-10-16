<script setup lang="ts" generic="T extends WorkspaceSelectValue">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NTreeSelect } from 'naive-ui'
import type { TreeSelectInst, TreeSelectOption } from 'naive-ui'
import { useThemeStore } from '../../store/theme-store'
import { workspaceSelectKey } from '../../utils/workspace-select'
import type { WorkspaceSelectValue } from '../../utils/workspace-select'
import { resolveWorkspaceTreeSelection, workspaceTreeOptions, workspaceTreeSelectTheme } from '../../utils/workspace-tree-select'
import type { WorkspaceTreeSelectOption } from '../../utils/workspace-tree-select'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue: T; options: readonly WorkspaceTreeSelectOption<T>[]; disabled?: boolean
  filterable?: boolean; placeholder?: string; size?: 'small' | 'medium'; ariaLabel?: string
}>(), {disabled: false, filterable: true, placeholder: '请选择', size: 'medium'})
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const select = ref<TreeSelectInst | null>(null)
const { isDarkTheme, colorPalette } = storeToRefs(useThemeStore())
const theme = computed(() => workspaceTreeSelectTheme(isDarkTheme.value, colorPalette.value))
const menuOptions = computed(() => workspaceTreeOptions(props.options))
function filter(pattern: string, option: TreeSelectOption): boolean {
  return String(option.searchText ?? option.label ?? '').toLowerCase().includes(pattern.trim().toLowerCase())
}
function update(key: unknown): void {
  const option = resolveWorkspaceTreeSelection(props.options, key, props.disabled)
  if (!option) return
  // v-model 先更新，联动筛选和分页才能读取本次选择；清空或过期回执不能绕过当前树。
  emit('update:modelValue', option.value)
  emit('change', option.value)
}
defineExpose({focus: () => select.value?.focus()})
</script>

<template>
  <span class="workspace-tree-select" role="group" :aria-label="ariaLabel">
    <NTreeSelect ref="select" v-bind="$attrs" to="body" :value="workspaceSelectKey(modelValue)"
      :options="menuOptions" :disabled="disabled" :filterable="filterable" :filter="filter"
      :placeholder="placeholder" :size="size" :theme-overrides="theme" show-path show-line
      :default-expand-all="false" :clearable="false" @update:value="update">
      <template #empty>暂无可选项</template>
    </NTreeSelect>
  </span>
</template>

<style scoped>
/* 分类树菜单独立滚动；触发框沿用公共下拉尺寸，避免全局输入样式覆盖搜索输入。 */
.workspace-tree-select { display:block; width:100%; min-width:0; font-weight:400; }
.workspace-tree-select :deep(.n-base-selection-overlay__wrapper) { font-weight:400; }
.workspace-tree-select :deep(input.n-base-selection-input) {
  min-height:0; border:0; border-radius:0; padding:0; background:transparent; outline:none; box-shadow:none;
}
</style>
