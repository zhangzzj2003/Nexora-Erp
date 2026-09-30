<script setup lang="ts" generic="T extends WorkspaceSelectValue">
import { computed, ref, watch, onScopeDispose } from 'vue'
import { storeToRefs } from 'pinia'
import { NSelect } from 'naive-ui'
import type { SelectInst } from 'naive-ui'
import type { TableDataset, TableRow } from '../../../../shared/erp-api'
import { usePiniaAppStore } from '../../store/app-store'
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
    remoteDataset?: TableDataset
    remoteFilters?: Record<string, string | number | boolean | null>
    modelValue: T
    options: readonly WorkspaceSelectOption<T>[]
    disabled?: boolean
    required?: boolean
    filterable?: boolean
    placeholder?: string
    size?: 'small' | 'medium'
    ariaLabel?: string
  }>(),
  { disabled: false, required: false, filterable: true, placeholder: '请选择', size: 'medium' }
)
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const select = ref<SelectInst | null>(null)
const invalid = ref(false)
const { isDarkTheme } = storeToRefs(useThemeStore())
const theme = computed(() => workspaceSelectTheme(isDarkTheme.value))
// 选择框按需远程搜索，保留空选项与当前选中项，避免一次加载所有客户或物料。
const appStore = usePiniaAppStore()
const remoteRows = ref<WorkspaceSelectOption<T>[]>([])
const remoteLoading = ref(false)
const remoteError = ref('')
let remotePage = 1
let remoteTotal = 0
let remoteQuery = ''
let requestVersion = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined
function optionFor(row: TableRow): WorkspaceSelectOption<T> {
  const value = row.id ?? row.code ?? row.work_order_id ?? row.order_id ?? row.material_issue_line_id
  const name = row.name ?? row.customer_name ?? row.product_name ?? row.party_name ?? row.material_name ?? row.full_name ?? row.username ?? row.label ?? ''
  const label = row.sku ? `${row.sku} · ${name}` : name ? `${row.id && !row.name && !row.username ? '#' + row.id + ' · ' : ''}${name}` : `#${value}`
  return { value: value as T, label }
}
async function loadOptions(query = '', page = 1): Promise<void> {
  if (!props.remoteDataset || typeof window === 'undefined' || !window.nexora) return
  const current = ++requestVersion
  remoteLoading.value = true
  try {
    remoteError.value = ''
    const result = await appStore.queryDataset({ dataset: props.remoteDataset, query, page, page_size: 100, filters: props.remoteFilters })
    if (current !== requestVersion) return
    appStore.hydrateDataset(props.remoteDataset, result.items)
    remotePage = result.page
    remoteTotal = result.total
    remoteQuery = query
    remoteRows.value = page === 1 ? result.items.map(optionFor) : [...remoteRows.value.slice(-100), ...result.items.map(optionFor)]
  } catch (error) {
    if (current === requestVersion) remoteError.value = error instanceof Error ? error.message : '选择项读取失败，请重试'
  } finally { if (current === requestVersion) remoteLoading.value = false }
}
function searchRemote(query: string): void {
  if (!props.remoteDataset) return
  ++requestVersion
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void loadOptions(query).catch(() => { remoteRows.value = [] }) }, 250)
}
onScopeDispose(() => { ++requestVersion; clearTimeout(searchTimer) })
watch(() => [props.remoteDataset, props.remoteFilters], () => { remoteRows.value = []; if (props.remoteDataset) void loadOptions() }, { deep: true, immediate: true })
const visibleOptions = computed(() => {
  if (!props.remoteDataset) return props.options
  const options = new Map<T, WorkspaceSelectOption<T>>()
  for (const option of props.options)
    if (option.value === null || option.value === 0 || option.value === '' || option.value === props.modelValue) options.set(option.value, option)
  for (const option of remoteRows.value) options.set(option.value, option)
  if (remotePage * 100 < remoteTotal) options.set('__load_more__' as T, { value: '__load_more__' as T, label: '继续加载下一页…' })
  return [...options.values()]
})
const menuOptions = computed(() =>
  visibleOptions.value.map((option) => ({ ...option, value: workspaceSelectKey(option.value) }))
)
const valid = computed(() => hasWorkspaceSelection(visibleOptions.value, props.modelValue))
function update(key: unknown): void {
  if (key === workspaceSelectKey('__load_more__')) { void loadOptions(remoteQuery, remotePage + 1); return }
  const option = resolveWorkspaceSelection(visibleOptions.value, key, props.disabled)
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
      :remote="Boolean(remoteDataset)"
      :loading="remoteLoading"
      @search="searchRemote"
      @update:show="show => { if (show && remoteDataset) void loadOptions().catch(() => { remoteRows = [] }) }"
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
    <small v-if="remoteError" role="alert">{{ remoteError }}</small>
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
