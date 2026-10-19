<script setup lang="ts" generic="T extends number | null">
import { computed, h, ref } from 'vue'
import type { SelectOption } from 'naive-ui'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import type { WorkspaceSelectOption } from '../../utils/workspace-select'
import { materialSelectOptions, matchesMaterialChoice } from '../../utils/material-selection'
import WorkspaceSelect from './WorkspaceSelect.vue'
import WorkspaceMaterialInfo from './WorkspaceMaterialInfo.vue'

// 组件只展示资料和回传编号；草稿及候选范围仍由 Pinia 和业务页面管理。
defineOptions({ inheritAttrs: false })
// 显式保留 undefined，避免 Vue 把未传入的布尔属性转成 false，影响普通表单。
const props = withDefaults(defineProps<{
  modelValue: T
  options?: readonly WorkspaceSelectOption<T>[]
  materials: readonly MaterialChoice[]
  categories?: readonly MaterialCategory[]
  disabled?: boolean
  required?: boolean
  placeholder?: string
  ariaLabel?: string
  // 由表格控制哪一行展示资料；未传入时保留普通业务表单的完整展示。
  compact?: boolean
}>(), { compact: undefined })
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T]; 'update:compact': [value: boolean] }>()
const source = computed(() => props.materials)
const directory = computed(() => props.categories ?? [])
const options = computed(() => props.options ?? source.value.map(item => ({ value: item.id as T, label: `${item.sku} · ${item.name}` })))
const enriched = computed(() => materialSelectOptions(options.value, source.value, directory.value))
const selected = computed(() => options.value.some(option => Object.is(option.value, props.modelValue))
  ? source.value.find(item => item.id === props.modelValue) : undefined)
const hasSelection = computed(() => typeof props.modelValue === 'number' && props.modelValue > 0)
const select = ref<{ focus: () => void } | null>(null)
function update(value: T): void {
  emit('update:modelValue', value)
  emit('change', value)
}
function filter(query: string, option: SelectOption): boolean {
  return matchesMaterialChoice(query, typeof option.searchText === 'string' ? option.searchText : String(option.label ?? '').toLowerCase())
}
function renderLabel(option: SelectOption, inTrigger: boolean) {
  // 触发框保持单行，菜单采用两行；文本节点避免把档案内容解释成 HTML。
  if (inTrigger || !option.description) return String(option.label ?? '')
  return h('span', { class: 'workspace-material-option' }, [
    h('span', { class: 'workspace-material-option__name', title: String(option.label) }, String(option.label)),
    h('span', { class: 'workspace-material-option__details', title: String(option.description) }, String(option.description))
  ])
}
defineExpose({ focus: () => select.value?.focus() })
</script>

<template>
  <span class="workspace-material-select">
    <WorkspaceSelect ref="select" v-bind="$attrs" :model-value="modelValue" :options="enriched"
      :disabled="disabled" :required="required" :placeholder="placeholder ?? '搜索编码、名称、规格、封装或料号'"
      :aria-label="ariaLabel" :filter="filter" :render-label="renderLabel" :option-height="60"
      @update:model-value="update" />
    <!-- 名称列和选料器复用同一份摘要及资料卡，选料器只回传受控行的收起状态。 -->
    <WorkspaceMaterialInfo v-if="hasSelection" :material="selected" :categories="directory" :compact="compact" :disabled="disabled"
      @update:compact="value => emit('update:compact', value)" />
  </span>
</template>

<style scoped>
/* 表格与普通表单共用紧凑资料卡，长规格和料号换行，不撑宽所在单元格。 */
.workspace-material-select { display: flex; flex-direction: column; gap: 8px; min-width: 0; width: 100%; font-weight: 400; }
</style>
<style>
/* 菜单传送到 body，使用全局唯一类名保证两行标签在弹窗和明暗主题下都生效。 */
.workspace-material-option { display: flex; flex-direction: column; gap: 4px; min-width: 0; width: 100%; line-height: 1.4; }
.workspace-material-option__name, .workspace-material-option__details { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-material-option__name { font-weight: 600; }
.workspace-material-option__details { color: var(--workspace-field-muted); font-size: 12px; }
</style>
