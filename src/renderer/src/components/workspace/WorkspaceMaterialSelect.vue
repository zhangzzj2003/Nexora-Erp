<script setup lang="ts" generic="T extends number | null">
import { computed, h, nextTick, ref, useId, watch } from 'vue'
import type { SelectOption } from 'naive-ui'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import type { WorkspaceSelectOption } from '../../utils/workspace-select'
import { hasMaterialDetails, materialChoiceFacts, materialSelectOptions, matchesMaterialChoice } from '../../utils/material-selection'
import WorkspaceSelect from './WorkspaceSelect.vue'
import AppButton from '../app/AppButton.vue'

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
const core = computed(() => selected.value ? materialChoiceFacts(selected.value, directory.value) : [])
const technical = computed(() => selected.value ? materialChoiceFacts(selected.value, directory.value, true) : [])
const summary = computed(() => enriched.value.find(option => Object.is(option.value, props.modelValue))?.description ?? '')
const expanded = ref(false)
const detailsId = useId()
const infoId = useId()
const select = ref<{ focus: () => void } | null>(null)
const infoToggle = ref<{ $el: HTMLElement } | null>(null)
// 新增行或切换查看对象时收起技术参数，避免旧行重新展开后仍占据大块空间。
watch(() => [props.modelValue, props.compact], () => { expanded.value = false })
function update(value: T): void {
  emit('update:modelValue', value)
  emit('change', value)
}
function toggleCompact(value: boolean): void {
  emit('update:compact', value)
  // 摘要与资料卡互相替换后，把键盘焦点交给新按钮，避免焦点落回页面顶部。
  void nextTick(() => { if (infoToggle.value?.$el instanceof HTMLElement) infoToggle.value.$el.focus() })
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
    <span v-if="selected && hasMaterialDetails(selected) && compact" class="workspace-material-summary" aria-label="物料资料摘要">
      <span class="workspace-material-summary__text" :title="summary">{{ summary }}</span>
      <AppButton ref="infoToggle" type="button" variant="text" size="small" :disabled="disabled" aria-expanded="false" :aria-controls="infoId"
        @click.prevent.stop="toggleCompact(false)">查看资料</AppButton>
    </span>
    <span v-else-if="selected && hasMaterialDetails(selected)" :id="infoId" class="workspace-material-facts" aria-label="当前物料资料">
      <span v-for="fact in core" :key="fact.key" class="workspace-material-fact">
        <span class="workspace-material-fact__label">{{ fact.label }}</span><span>{{ fact.value }}</span>
      </span>
      <span class="workspace-material-actions">
        <AppButton type="button" variant="text" size="small" class="workspace-material-expand" :disabled="disabled"
          :aria-expanded="expanded" :aria-controls="detailsId" @click.prevent.stop="expanded = !expanded">
          {{ expanded ? '收起详情' : '展开详情' }}
        </AppButton>
        <AppButton v-if="compact !== undefined" ref="infoToggle" type="button" variant="text" size="small" :disabled="disabled" aria-expanded="true" :aria-controls="infoId"
          @click.prevent.stop="toggleCompact(true)">收起资料</AppButton>
      </span>
      <span v-if="expanded" :id="detailsId" class="workspace-material-technical">
        <span v-for="fact in technical" :key="fact.key" class="workspace-material-fact" :class="{ 'workspace-material-fact--wide': fact.key === 'notes' }">
          <span class="workspace-material-fact__label">{{ fact.label }}</span><span>{{ fact.value }}</span>
        </span>
      </span>
    </span>
    <span v-else-if="hasSelection" class="workspace-material-unavailable" role="status">详细资料暂不可用</span>
  </span>
</template>

<style scoped>
/* 表格与普通表单共用紧凑资料卡，长规格和料号换行，不撑宽所在单元格。 */
.workspace-material-select { display: flex; flex-direction: column; gap: 8px; min-width: 0; width: 100%; font-weight: 400; }
.workspace-material-facts, .workspace-material-technical { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; }
.workspace-material-facts { padding: 10px; border: 1px solid var(--workspace-field-border); border-radius: 8px; background: var(--app-accent-tint); font-size: 12px; line-height: 1.5; }
.workspace-material-fact { display: flex; flex-direction: column; gap: 2px; min-width: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.workspace-material-fact__label, .workspace-material-unavailable { color: var(--workspace-field-muted); font-size: 12px; }
.workspace-material-actions, .workspace-material-technical, .workspace-material-fact--wide { grid-column: 1 / -1; }
.workspace-material-actions { display: flex; align-items: center; gap: 14px; }
.workspace-material-expand { justify-self: start; }
.workspace-material-technical { padding-top: 10px; border-top: 1px solid var(--workspace-field-border); }
/* 旧行只保留一行辨认摘要，查看按钮独立显示，不被长规格或料号挤出。 */
.workspace-material-summary { display: flex; align-items: center; gap: 10px; min-width: 0; color: var(--workspace-field-muted); font-size: 12px; }
.workspace-material-summary__text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-material-summary > :last-child { flex-shrink: 0; }
</style>
<style>
/* 菜单传送到 body，使用全局唯一类名保证两行标签在弹窗和明暗主题下都生效。 */
.workspace-material-option { display: flex; flex-direction: column; gap: 4px; min-width: 0; width: 100%; line-height: 1.4; }
.workspace-material-option__name, .workspace-material-option__details { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-material-option__name { font-weight: 600; }
.workspace-material-option__details { color: var(--workspace-field-muted); font-size: 12px; }
</style>
