<script lang="ts">
import { VxeUI } from '@vxe-ui/core'
import zhCN from 'vxe-table/es/locale/lang/zh-CN'

// 分组件加载时显式安装中文文案，避免表格内置提示回退为语言键。
VxeUI.setI18n('zh-CN', zhCN)
</script>

<script setup lang="ts" generic="TRow extends object">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import VxeColumn from 'vxe-table/es/column'
import VxeTable from 'vxe-table/es/table'
import 'vxe-table/es/table/style.css'
import WorkspacePagination from './WorkspacePagination.vue'
import { tableScrollbarMetrics } from '../../utils/table-scrollbar'

import type { VxeTableInstance } from 'vxe-table'
import { resolveTableColumns, type WorkspaceTableColumn } from '../../utils/table-columns'

const props = withDefaults(defineProps<{
  title: string
  // 主列表可隐藏重复标题，保留页面顶部品牌标题及表格无障碍名称。
  showTitle?: boolean
  description?: string
  columns?: readonly WorkspaceTableColumn[]
  data?: TRow[]
  emptyText?: string
  error?: string
  loading?: boolean
  // 开启分页时只展示当前页数据，不在组件内切割完整数组。
  pagination?: { page: number; pageSize: number; total: number; disabled?: boolean }
  minTableWidth?: number
}>(), {
  showTitle: true,
  description: '',
  columns: () => [],
  data: () => [],
  emptyText: '暂无数据',
  error: '',
  loading: false,
  minTableWidth: 580
})

const emit = defineEmits<{ pageChange: [page: number, pageSize: number] }>()

const tableRef = ref<VxeTableInstance<TRow> | null>(null)
const resolvedColumns = computed(() => resolveTableColumns(props.columns))
const hasFixedColumns = computed(() => resolvedColumns.value.some(column => column.fixed))
// 固定列由 VXE 自身布局，外壳保持视口宽度，不能再把整张表撑宽后滚动。
const defaultColumnWidth = computed(() => Math.ceil(props.minTableWidth / Math.max(1, props.columns.length)))
const scrollContainer = ref<HTMLElement | null>(null)
const scrollMax = ref(0)
const scrollPosition = ref(0)
const scrollThumbWidth = ref(44)
let resizeObserver: ResizeObserver | null = null

function updateScrollbar(): void {
  const container = scrollContainer.value
  if (!container) return
  const viewport = hasFixedColumns.value ? tableRef.value?.getScrollData() : container
  if (!viewport) return
  const metrics = tableScrollbarMetrics(viewport.clientWidth, viewport.scrollWidth)
  scrollMax.value = metrics.max
  scrollThumbWidth.value = metrics.thumbWidth
  scrollPosition.value = viewport.scrollLeft
}

function scrollFromControl(event: Event): void {
  const container = scrollContainer.value
  const position = Number((event.target as HTMLInputElement).value)
  if (hasFixedColumns.value) void tableRef.value?.scrollTo(position)
  else if (container) container.scrollLeft = position
}

function syncScrollPosition(): void {
  scrollPosition.value = hasFixedColumns.value
    ? tableRef.value?.getScrollData().scrollLeft ?? 0
    : scrollContainer.value?.scrollLeft ?? 0
}

// vxe 挂载后才确定实际列宽；同时观察窗口和表格宽度，保持拖动条比例准确。
onMounted(async () => {
  await nextTick()
  const container = scrollContainer.value
  if (!container) return
  resizeObserver = new ResizeObserver(() => { void refreshScrollbar() })
  resizeObserver.observe(container)
  const table = container.querySelector('.workspace-vxe-table')
  if (table) resizeObserver.observe(table)
  await refreshScrollbar()
})
onUnmounted(() => resizeObserver?.disconnect())
async function refreshScrollbar(): Promise<void> {
  await nextTick()
  // 等列宽和数据行完成重排后读取真实范围，窗口缩放或筛选后不会残留过期位置。
  if (hasFixedColumns.value) await tableRef.value?.recalculate()
  updateScrollbar()
}
watch(() => [props.minTableWidth, props.columns, props.data.length, props.error], () => {
  void refreshScrollbar()
}, { deep: true })

// 数据类型从页面传入的行推断，业务单元格继续获得原本的字段类型。
defineSlots<{
  heading?: () => unknown
  actions?: () => unknown
  filters?: () => unknown
  // 查询按钮与列表操作放进同一按钮组，窄窗时一起换行。
  filterActions?: () => unknown
  beforeTable?: () => unknown
  empty?: () => unknown
  errorActions?: () => unknown
  footer?: () => unknown
  [name: `cell-${string}`]: (props: { row: TRow }) => unknown
}>()

// 所有业务列表只提供数据与单元格插槽；表格的渲染、空状态和加载状态由这里统一管理。
</script>

<template>
  <section class="card workspace-table">
    <header v-if="showTitle || description || $slots.heading || ($slots.actions && !$slots.filters && !$slots.filterActions)" class="workspace-table-heading">
      <div v-if="showTitle || description || $slots.heading">
        <slot name="heading">
          <h2 v-if="showTitle">{{ title }}</h2>
          <p v-if="description" class="muted">{{ description }}</p>
        </slot>
      </div>
      <div v-if="$slots.actions && !$slots.filters && !$slots.filterActions" class="workspace-table-actions">
        <slot name="actions" />
      </div>
    </header>
    <!-- 条件与操作共用工具栏，避免单个新建或导出按钮独占一行。 -->
    <div v-if="$slots.filters || $slots.filterActions" class="workspace-table-toolbar">
      <div v-if="$slots.filters" class="workspace-table-filters">
        <slot name="filters" />
      </div>
      <div v-if="$slots.filterActions || $slots.actions" class="workspace-table-toolbar-actions">
        <slot name="filterActions" />
        <slot name="actions" />
      </div>
    </div>
    <div v-if="$slots.beforeTable" class="workspace-table-before">
      <slot name="beforeTable" />
    </div>
    <div ref="scrollContainer" class="table-wrap" :class="{ 'has-fixed-columns': hasFixedColumns }" @scroll.passive="syncScrollPosition">
      <span v-if="loading" class="workspace-table-status" role="status">正在加载…</span>
      <VxeTable ref="tableRef" class="workspace-vxe-table" @scroll="syncScrollPosition" :aria-label="title" :aria-busy="loading" :data="error ? [] : data" :loading="loading" :style="hasFixedColumns ? undefined : { minWidth: `${minTableWidth}px` }"
        :scrollbar-config="hasFixedColumns ? { x: { visible: false } } : undefined">
        <VxeColumn v-for="column in resolvedColumns" :key="column.key" :field="column.key" :title="column.title"
          :fixed="column.fixed || undefined" :width="column.width || (hasFixedColumns ? defaultColumnWidth : undefined)">
          <template v-if="$slots[`cell-${column.key}`]" #default="{ row }">
            <slot :name="`cell-${column.key}`" :row="row" />
          </template>
        </VxeColumn>
        <template #empty>
          <div v-if="!loading" class="workspace-table-empty" :class="{ 'is-error': error }" :role="error ? 'alert' : 'status'">
            <span class="workspace-table-empty-icon" aria-hidden="true">
              <svg viewBox="0 0 40 40" fill="none">
                <rect x="6" y="7" width="28" height="26" rx="4" stroke="currentColor" stroke-width="1.8" />
                <path d="M6 15h28M15 15v18M19 21h10M19 27h7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
              </svg>
            </span>
            <div class="workspace-table-empty-copy">
              <template v-if="error">
                <strong>数据加载失败</strong>
                <span>{{ error }}</span>
                <slot name="errorActions" />
              </template>
              <slot v-else name="empty">{{ emptyText }}</slot>
            </div>
          </div>
        </template>
        <template #loading><div class="workspace-table-loading" role="status">正在加载…</div></template>
      </VxeTable>
    </div>
    <input v-if="scrollMax > 0" class="workspace-table-scrollbar" type="range" min="0" :max="scrollMax" :value="scrollPosition"
      :style="{ '--scroll-thumb-width': `${scrollThumbWidth}px` }" :aria-label="`${title}表格横向滚动`" @input="scrollFromControl" />
    <footer v-if="pagination || $slots.footer" class="workspace-table-footer">
      <WorkspacePagination v-if="pagination" v-bind="pagination" :disabled="loading || pagination.disabled" @change="(page, size) => emit('pageChange', page, size)" />
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.workspace-table-heading { display: flex; justify-content: space-between; align-items: start; gap: 18px; margin-bottom: 20px; }
.workspace-table-heading h2 { margin: 0; }
.workspace-table-heading .muted { margin: 0; line-height: 1.6; }
.workspace-table-heading h2 + .muted { margin-top: 8px; }
.workspace-table-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-left: auto; }
/* 筛选条件按合理宽度换行；操作按钮始终成组靠右，并与输入框底边对齐。 */
.workspace-table-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 16px; margin: 0 0 16px; padding: 16px; border: 1px solid #e4ebee; border-radius: 11px; background: #f8fafb; }
.workspace-table-filters { display: flex; flex: 1 1 560px; min-width: 0; align-items: end; gap: 12px; flex-wrap: wrap; }
.workspace-table-filters :deep(label) { flex: 1 1 170px; min-width: 0; max-width: 240px; }
.workspace-table-filters :deep(label:only-child) { max-width: 320px; }
.workspace-table-toolbar-actions { display: flex; flex: 0 0 auto; align-items: center; justify-content: flex-end; gap: 10px; margin-left: auto; }
.workspace-table-toolbar :deep(button) { white-space: nowrap; }
.workspace-table-filters :deep(input), .workspace-table-filters :deep(select) { min-width: 0; width: 100%; }
:root[data-theme='dark'] .workspace-table-toolbar { border-color: #30445b; background: #192a40; }
.workspace-table-before { margin-bottom: 20px; }
.workspace-table-before:empty { display: none; }
.workspace-table-footer { margin-top: 16px; }
.workspace-table-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.workspace-table-loading { padding: 20px; color: var(--vxe-ui-font-color); text-align: center; }
.workspace-table-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 180px; padding: 22px; color: #607289; text-align: center; }
/* 空状态图标与底色、描边共用主题变量，明暗模式不再覆盖为固定青绿；错误状态继续使用红色。 */
.workspace-table-empty-icon { display: grid; place-items: center; width: 46px; height: 46px; border: 1px solid var(--app-accent-ring); border-radius: 13px; background: var(--app-accent-tint); color: var(--workspace-field-accent); }
.workspace-table-empty-icon svg { width: 31px; height: 31px; }
.workspace-table-empty-copy { display: grid; justify-items: center; gap: 5px; max-width: 480px; font-size: 13px; line-height: 1.5; }
.workspace-table-empty-copy strong { color: #263950; font-size: 14px; }
.workspace-table-empty-copy span { color: #788ba0; }
.workspace-table-empty.is-error .workspace-table-empty-icon { border-color: #f1d8d5; background: #fff1ef; color: #c45a53; }
.workspace-table-empty.is-error .workspace-table-empty-copy strong { color: #9e3934; }
.table-wrap { overflow-x: auto; overflow-y: hidden; border-radius: 11px; scrollbar-width: none; }
.table-wrap.has-fixed-columns { overflow: clip; }
.table-wrap::-webkit-scrollbar { display: none; }
.workspace-table-scrollbar { display: block; appearance: none; width: 100%; min-height: 14px; height: 14px; margin: 10px 0 0; padding: 2px; border: 1px solid #d2dde5; border-radius: 8px; background: #e4ebf0; cursor: ew-resize; }
.workspace-table-scrollbar::-webkit-slider-thumb { appearance: none; width: var(--scroll-thumb-width); height: 10px; border: 0; border-radius: 6px; background: #61869c; box-shadow: 0 1px 2px #28465b38; }
.workspace-table-scrollbar::-moz-range-thumb { width: var(--scroll-thumb-width); height: 10px; border: 0; border-radius: 6px; background: #61869c; box-shadow: 0 1px 2px #28465b38; }
.workspace-table-scrollbar:hover::-webkit-slider-thumb { background: #2c7183; }
.workspace-table-scrollbar:active::-webkit-slider-thumb { background: var(--workspace-field-accent); }
.workspace-table-scrollbar:focus-visible { outline: 2px solid var(--workspace-field-accent); outline-offset: 3px; }
@media (max-width: 650px) {
  .workspace-table-heading { align-items: stretch; flex-direction: column; }
  .workspace-table-filters :deep(label), .workspace-table-filters :deep(label:only-child) { max-width: none; }
  .workspace-table-toolbar-actions { flex-wrap: wrap; max-width: 100%; }
  .workspace-table-actions { margin-left: 0; }
}
</style>

<style>
/* 公共表格统一匹配工作台明暗主题，并撤销原生表格规则对 vxe 行高的影响。 */
.workspace-vxe-table {
  /* 按需加载未提供边框宽度默认值，缺失时分隔线渐变会铺满整个单元格。 */
  --vxe-ui-table-border-width: 1px;
  --vxe-ui-font-color: #263950;
  --vxe-ui-font-primary-color: var(--workspace-field-accent);
  --vxe-ui-layout-background-color: #fff;
  --vxe-ui-table-header-background-color: #f1f5f7;
  --vxe-ui-table-header-font-color: #52657b;
  --vxe-ui-table-border-color: #e5edf1;
  border: 1px solid #e5edf1;
  border-radius: 11px;
  overflow: hidden;
}
.workspace-vxe-table table { border-collapse: separate; border-spacing: 0; }
/* 弹窗关闭时浏览器会恢复行按钮焦点；外层只裁切，不允许隐式滚动把表头推走。 */
/* 表格实际滚动仍由 VXE 的表体容器和共享横向滚动条处理。 */
.workspace-vxe-table .vxe-table--viewport-wrapper { overflow: clip; }
/* clip 不会像 hidden 自动缩小 flex 子项，显式归零最小宽度才能由 VXE 识别横向溢出。 */
.has-fixed-columns .vxe-table--viewport-wrapper { min-width: 0; }
.workspace-vxe-table :is(th, td) { padding: 0; border-bottom: 0; vertical-align: middle; }
/* 表头与内容共用列内边距，首列再多留一点空间，避免标题贴住表格边框。 */
.workspace-vxe-table :is(.vxe-header--column, .vxe-body--column) > .vxe-cell { padding-inline: 14px; }
.workspace-vxe-table :is(.vxe-header--column, .vxe-body--column):first-child > .vxe-cell { padding-left: 18px; }
/* 数据行保留上下留白，表单和多行明细不会贴着分隔线。 */
.workspace-vxe-table .vxe-body--column > .vxe-cell { padding-block: 12px; }
/* 单号下的状态、创建人与备注各占一行，避免明细挤成难以扫描的一段文字。 */
.workspace-vxe-table .vxe-body--column .vxe-cell small { display: block; margin: 4px 0 0; line-height: 1.5; }
/* 明细逐条排布；行内表单保持纵向阅读，长文本不会撑破固定列宽。 */
.workspace-vxe-table .workspace-record-lines { display: grid; gap: 8px; }
.workspace-vxe-table .workspace-record-lines > span + span { padding-top: 8px; border-top: 1px solid var(--vxe-ui-table-border-color); }
.workspace-vxe-table .vxe-body--column .muted { margin: 6px 0 0; line-height: 1.6; }
.workspace-vxe-table .vxe-body--column .inline-form { display: flex; flex-direction: column; align-items: stretch; gap: 10px; margin-top: 10px; }
.workspace-vxe-table .vxe-body--column .inline-form { margin-bottom: 0; padding-bottom: 0; border-bottom: 0; }
.workspace-vxe-table .vxe-body--column .inline-form label { min-width: 0; }
.workspace-vxe-table .vxe-body--column .form-actions { flex-wrap: wrap; justify-content: flex-start; gap: 8px; margin: 0; }
.workspace-vxe-table .vxe-body--column button { white-space: nowrap; }
.workspace-vxe-table .vxe-body--column :is(input,select) { min-width: 0; max-width: 100%; }
/* 数据表的列标题承担定位作用，提高字号与字重，避免浅色背景上难以辨认。 */
.workspace-vxe-table .vxe-header--column > .vxe-cell { color: #38516a; font-size: 13px; font-weight: 700; }
/* 空状态占据完整表格宽度，避免窄小的默认占位字落在第一行下面。 */
.workspace-vxe-table .vxe-table--empty-content { width: 100%; }
.workspace-vxe-table .vxe-table--empty-placeholder,
.workspace-vxe-table .vxe-table--empty-block { min-height: 180px; }
:root[data-theme='dark'] .workspace-table-empty { color: #a3b4cc; }
:root[data-theme='dark'] .workspace-table-empty-copy strong { color: #e6edf8; }
:root[data-theme='dark'] .workspace-table-empty-copy span { color: #a3b4cc; }
:root[data-theme='dark'] .workspace-table-empty.is-error .workspace-table-empty-icon { border-color: #70423f; background: #432a30; color: #ffaaa2; }
:root[data-theme='dark'] .workspace-table-empty.is-error .workspace-table-empty-copy strong { color: #ffaaa2; }
:root[data-theme='dark'] .workspace-table-scrollbar { border-color: #38516a; background: #263b52; }
:root[data-theme='dark'] .workspace-table-scrollbar::-webkit-slider-thumb { background: #82a9bd; box-shadow: none; }
:root[data-theme='dark'] .workspace-table-scrollbar::-moz-range-thumb { background: #82a9bd; box-shadow: none; }
:root[data-theme='dark'] .workspace-table-scrollbar:hover::-webkit-slider-thumb { background: #a5c7d7; }
:root[data-theme='dark'] .workspace-vxe-table .vxe-header--column > .vxe-cell { color: #d6e4f2; }
:root[data-theme='dark'] .workspace-vxe-table {
  --vxe-ui-font-color: #e6edf8;
  --vxe-ui-font-primary-color: var(--workspace-field-accent);
  --vxe-ui-layout-background-color: #142238;
  --vxe-ui-table-header-background-color: #203047;
  --vxe-ui-table-header-font-color: #b3c4d8;
  --vxe-ui-table-border-color: #2d3e57;
  border-color: #2d3e57;
}
</style>
