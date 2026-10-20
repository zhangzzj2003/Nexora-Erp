<script setup lang="ts" generic="T extends number | null">
import type { MaterialUse } from '../../../../shared/material-uses'
import { materialUseOptions } from '../../utils/material-use'
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
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
  // 新建业务显式指定用途；库存、历史单据及生产耗料不套用销售或生产资格。
  use?: MaterialUse
  categories?: readonly MaterialCategory[]
  disabled?: boolean
  required?: boolean
  placeholder?: string
  ariaLabel?: string
  // 由表格控制哪一行展示资料；未传入时保留普通业务表单的完整展示。
  compact?: boolean
  // 表格展示由业务页面主动启用，普通物料下拉继续使用原有两行菜单。
  menuLayout?: 'list' | 'table'
}>(), { compact: undefined })
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T]; 'update:compact': [value: boolean] }>()
const source = computed(() => props.materials)
const directory = computed(() => props.categories ?? [])
const options = computed(() => props.options ?? source.value.map(item => ({ value: item.id as T, label: `${item.sku} · ${item.name}` })))
// 名称补全后再加用途提示，防止资料格式化覆盖不可用原因。
const enriched = computed(() => materialUseOptions(materialSelectOptions(options.value, source.value, directory.value),
  source.value, props.use, props.modelValue))
const selected = computed(() => options.value.some(option => Object.is(option.value, props.modelValue))
  ? source.value.find(item => item.id === props.modelValue) : undefined)
const hasSelection = computed(() => typeof props.modelValue === 'number' && props.modelValue > 0)
const select = ref<{ focus: () => void } | null>(null)
const root = ref<HTMLElement | null>(null)
const tableWidth = ref(640)
function resizeTableMenu(): void {
  if (props.menuLayout !== 'table' || !root.value) return
  const rect = root.value.getBoundingClientRect()
  // NSelect 会左右翻转但不会水平平移；按较宽一侧限制宽度，给窗口边缘保留间距。
  const available = Math.max(window.innerWidth - rect.left, rect.right) - 16
  tableWidth.value = Math.max(0, Math.min(640, window.innerWidth - 32, available))
}
onMounted(() => window.addEventListener('resize', resizeTableMenu))
onBeforeUnmount(() => window.removeEventListener('resize', resizeTableMenu))
function update(value: T): void {
  emit('update:modelValue', value)
  emit('change', value)
}
function filter(query: string, option: SelectOption): boolean {
  return matchesMaterialChoice(query, typeof option.searchText === 'string' ? option.searchText : String(option.label ?? '').toLowerCase())
}
function renderLabel(option: SelectOption, inTrigger: boolean) {
  if (!inTrigger && props.menuLayout === 'table') {
    const sku = typeof option.sku === 'string' ? option.sku : ''
    const label = String(option.label ?? '')
    // 只移除已知编号前缀，保留名称中的分隔符及用途变更后的禁用提示。
    const name = sku && label.startsWith(`${sku} · `) ? label.slice(sku.length + 3) : label
    return h('span', { class: 'workspace-material-table__row' }, [
      h('span', { class: 'workspace-material-table__sku' }, sku || '—'),
      h('span', { class: 'workspace-material-table__content' }, [
        h('span', { class: 'workspace-material-table__name' }, name),
        h('span', { class: 'workspace-material-table__details' }, String(option.description || '详细资料暂不可用'))
      ])
    ])
  }
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
  <span ref="root" class="workspace-material-select">
    <WorkspaceSelect ref="select" v-bind="$attrs" :model-value="modelValue" :options="enriched"
      :disabled="disabled" :required="required" :placeholder="placeholder ?? '搜索编码、名称、规格、封装或料号'"
      :aria-label="ariaLabel" :filter="filter" :render-label="renderLabel" :option-height="60"
      :consistent-menu-width="menuLayout !== 'table'"
      :menu-props="menuLayout === 'table' ? { class: 'workspace-material-table', style: { width: `${tableWidth}px` } } : undefined"
      @update:show="resizeTableMenu"
      @update:model-value="update">
      <template v-if="menuLayout === 'table'" #header>
        <div class="workspace-material-table__header" aria-hidden="true"><span>编号</span><span>物料名称 / 详情</span></div>
      </template>
    </WorkspaceSelect>
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
/* 菜单独立于触发框宽度，并由原有浮层定位避让窗口边缘；长文本完整换行。 */
.workspace-material-table.n-base-select-menu { width: min(640px, calc(100vw - 32px)); }
.workspace-material-table.n-base-select-menu .n-base-select-menu__header { padding: 0; }
.workspace-material-table__header, .workspace-material-table__row {
  display: grid; grid-template-columns: minmax(0, 180px) minmax(0, 1fr); column-gap: 16px;
}
.workspace-material-table__header { padding: 10px 32px 10px 12px; font-size: 12px; font-weight: 600; color: var(--workspace-field-muted); }
.workspace-material-table.n-base-select-menu .n-base-select-option {
  height: auto; min-height: 68px; padding-top: 10px; padding-bottom: 10px;
}
.workspace-material-table.n-base-select-menu .n-base-select-option .n-base-select-option__content { width: 100%; min-width: 0; white-space: normal; }
.workspace-material-table__row { width: 100%; line-height: 1.5; white-space: normal; }
.workspace-material-table__sku { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.workspace-material-table__sku, .workspace-material-table__header > :first-child { padding-right: 12px; border-right: 1px solid var(--workspace-field-border); }
.workspace-material-table__content { display: flex; flex-direction: column; gap: 4px; min-width: 0; overflow-wrap: anywhere; }
.workspace-material-table__name { font-weight: 600; }
.workspace-material-table__details { color: var(--workspace-field-muted); font-size: 12px; }
.workspace-material-table .n-base-select-option + .n-base-select-option { border-top: 1px solid var(--workspace-field-border); }
@media (max-width: 600px) {
  .workspace-material-table__header, .workspace-material-table__row { grid-template-columns: minmax(0, 32%) minmax(0, 1fr); column-gap: 12px; }
}
</style>
