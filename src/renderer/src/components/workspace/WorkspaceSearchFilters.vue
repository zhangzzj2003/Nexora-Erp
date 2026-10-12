<script setup lang="ts" generic="T extends Record<string, WorkspaceSelectValue>">
import { NDatePicker } from 'naive-ui'
import AppInput from '../app/AppInput.vue'
import AppButton from '../app/AppButton.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import { dateOutsideRange, datePickerString, vDateField } from '../../utils/date-field'
import { updateWorkspaceSearchFilter } from '../../utils/workspace-search-filters'
import type { WorkspaceSearchFilterField } from '../../utils/workspace-search-filters'
import type { WorkspaceSelectValue } from '../../utils/workspace-select'

// 各页面按需传字段；搜索、选择器和日期统一复用现有控件及主题。
const props = withDefaults(defineProps<{
  query: string
  filters: T
  fields?: readonly WorkspaceSearchFilterField[]
  searchLabel?: string
  searchPlaceholder?: string
  disabled?: boolean
  resetDisabled?: boolean
  issue?: string
}>(), { fields: () => [], searchLabel: '搜索', searchPlaceholder: '输入关键词', disabled: false, resetDisabled: false, issue: '' })
const emit = defineEmits<{
  'update:query': [value: string]
  'update:filters': [value: T]
  reset: []
}>()
function updateQuery(value: string): void {
  if (!props.disabled) emit('update:query', value)
}
function updateField(field: WorkspaceSearchFilterField, value: WorkspaceSelectValue): void {
  const next = updateWorkspaceSearchFilter(props.filters, field, value, props.disabled)
  if (next) emit('update:filters', next)
}
function dateValue(key?: string): string {
  const value = key ? props.filters[key] : ''
  return typeof value === 'string' ? value : ''
}
function reset(): void {
  // 重置由页面决定是否同时清除状态概览，组件不接触 Pinia 的业务快照或草稿。
  if (!props.disabled && !props.resetDisabled) emit('reset')
}
</script>

<template>
  <div class="workspace-search-filters" role="group" aria-label="搜索与筛选">
    <label class="workspace-search-field">{{ searchLabel }}
      <AppInput :model-value="query" type="search" :placeholder="searchPlaceholder"
        :aria-label="searchLabel" :disabled="disabled" @update:model-value="updateQuery" />
    </label>
    <label v-for="field in fields" :key="field.key" class="workspace-filter-field">{{ field.label }}
      <WorkspaceSelect v-if="field.kind === 'select'" :model-value="filters[field.key] ?? null"
        :options="field.options" :aria-label="field.label" :disabled="disabled"
        @update:model-value="value => updateField(field, value)" />
      <NDatePicker v-else v-date-field="{ min: dateValue(field.minKey) || undefined, max: dateValue(field.maxKey) || undefined }"
        to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" clearable
        :formatted-value="dateValue(field.key) || null" :aria-label="field.label" :disabled="disabled"
        :is-date-disabled="(timestamp: number) => dateOutsideRange(timestamp, dateValue(field.minKey) || undefined, dateValue(field.maxKey) || undefined)"
        @update:formatted-value="value => updateField(field, datePickerString(value))" />
    </label>
    <AppButton :disabled="disabled || resetDisabled" @click="reset">重置</AppButton>
    <p v-if="issue" class="workspace-filter-issue" role="alert">{{ issue }}</p>
  </div>
</template>

<style scoped>
/* 工具栏可换行，窄窗口中每个字段仍能完整操作，提示独占一行。 */
.workspace-search-filters { display: flex; flex: 1 1 0; min-width: 0; align-items: end; flex-wrap: wrap; gap: 12px; }
.workspace-search-filters > .workspace-search-field { flex: 1 1 260px; max-width: 320px; }
.workspace-search-filters > .workspace-filter-field { flex: 1 1 150px; max-width: 200px; }
.workspace-filter-issue { flex: 1 1 100%; margin: 0; color: #c45a53; font-size: 13px; }
:root[data-theme='dark'] .workspace-filter-issue { color: #ffaaa2; }
@media (max-width: 760px) {
  .workspace-search-filters > .workspace-search-field,
  .workspace-search-filters > .workspace-filter-field { max-width: none; }
}
</style>
