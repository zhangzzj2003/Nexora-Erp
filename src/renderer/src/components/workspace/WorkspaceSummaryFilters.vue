<script lang="ts">
// 统计组件只负责展示和选择，各页面定义自己的业务分组与数量口径。
export interface WorkspaceSummaryFilterOption<TKey extends string = string> {
  key: TKey
  label: string
  count: number
  hint: string
  tone?: 'pending' | 'success' | 'neutral' | 'reversed'
}
</script>

<script setup lang="ts" generic="TKey extends string">
import AppButton from '../app/AppButton.vue'
const props = withDefaults(defineProps<{
  modelValue: TKey
  options: readonly WorkspaceSummaryFilterOption<TKey>[]
  label?: string
  hint?: string
}>(), { label: '单据概览与快速筛选', hint: '全部单据统计 · 点击快速筛选' })
const emit = defineEmits<{ 'update:modelValue': [key: TKey] }>()
function select(key: TKey): void {
  // 拒绝过期或重复选择，避免无效选项触发列表重置。
  if (key !== props.modelValue && props.options.some(option => option.key === key)) emit('update:modelValue', key)
}
</script>

<template>
  <section class="workspace-summary" :aria-label="label">
    <div class="workspace-summary-filters" role="group" aria-label="状态筛选"
      :style="{ '--summary-columns': Math.max(1, Math.min(options.length, 5)),
        '--summary-columns-compact': Math.max(1, Math.min(options.length, 3)),
        '--summary-columns-narrow': Math.max(1, Math.min(options.length, 2)) }">
      <AppButton v-for="option in options" :key="option.key" type="button" variant="plain"
        class="summary-filter" :class="[{ 'is-selected': option.key === modelValue }, `summary-filter--${option.tone ?? 'all'}`]"
        :aria-pressed="option.key === modelValue" :aria-label="`${option.label}，${option.count} 条`"
        :title="option.hint" @click="select(option.key)">
        <span class="summary-filter-label">{{ option.label }}</span>
        <strong class="summary-filter-count">{{ option.count }}</strong>
      </AppButton>
    </div>
    <p v-if="hint" class="summary-filter-hint">{{ hint }}</p>
  </section>
</template>

<style scoped>
/* 统计与标题共用工作台表面，数字色调对应业务状态；选中项通过边框与浅底强调。 */
.workspace-summary-filters { display: grid; grid-template-columns: repeat(var(--summary-columns), minmax(0, 1fr)); gap: 8px; }
/* 概览卡片沿用工作台指标的 14px 圆角，背景、边框与选中描边共享同一轮廓。 */
.summary-filter { --summary-tone: var(--workspace-field-accent); width: 100%; min-width: 0; height: auto; padding: 14px 16px; border: 1px solid var(--workspace-field-border); border-radius: 14px; background: var(--workspace-field-background); text-align: left; }
.summary-filter :deep(.n-button__content) { width: 100%; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.summary-filter-label { color: var(--workspace-field-muted); font-size: 12px; font-weight: 500; }
.summary-filter-count { color: var(--summary-tone); font-size: 27px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
.summary-filter--pending { --summary-tone: #946000; }
.summary-filter--success { --summary-tone: #16734d; }
.summary-filter--neutral { --summary-tone: #626d7e; }
.summary-filter--reversed { --summary-tone: #7851ad; }
.summary-filter:is(:hover, :focus-visible), .summary-filter.is-selected { border-color: var(--workspace-field-accent); background: color-mix(in srgb, var(--workspace-field-accent) 12%, var(--workspace-field-background)); }
.summary-filter.is-selected .summary-filter-label { color: var(--workspace-field-accent); font-weight: 650; }
.summary-filter:focus-visible { outline: 2px solid var(--workspace-field-accent); outline-offset: 2px; }
.summary-filter-hint { margin: 8px 0 0; color: var(--workspace-field-muted); font-size: 11px; text-align: right; }
:root[data-theme='dark'] .summary-filter--pending { --summary-tone: #efc16a; }
:root[data-theme='dark'] .summary-filter--success { --summary-tone: #69d8aa; }
:root[data-theme='dark'] .summary-filter--neutral { --summary-tone: #b1bccd; }
:root[data-theme='dark'] .summary-filter--reversed { --summary-tone: #c2a4ef; }
/* 列数跟随统计项数量，其他页面只传数据即可复用；根据标题右侧实际可用空间换行，不依赖整窗宽度。 */
@container (max-width: 520px) { .workspace-summary-filters { grid-template-columns: repeat(var(--summary-columns-compact), minmax(0, 1fr)); } }
@container (max-width: 340px) { .workspace-summary-filters { grid-template-columns: repeat(var(--summary-columns-narrow), minmax(0, 1fr)); } }
</style>
