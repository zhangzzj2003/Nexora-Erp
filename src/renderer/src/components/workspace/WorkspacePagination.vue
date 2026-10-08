<script setup lang="ts">
import { computed, h } from 'vue'
import { NPagination } from 'naive-ui'
import type { PaginationRenderLabel } from 'naive-ui'

// 公共分页只发送查询意图，不截取业务数据；已有本地和服务端分页都沿用 change 接口。
const props = defineProps<{ page: number; pageSize: number; total: number; disabled?: boolean }>()
const emit = defineEmits<{ change: [page: number, pageSize: number] }>()
const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
// 补充 30/40 条，同时保留已有列表的 50/100 条选项。
const pageSizes = [10, 20, 30, 40, 50, 100]
function changePage(page: number): void {
  if (props.disabled || !Number.isInteger(page) || page < 1 || page > pageCount.value || page === props.page) return
  emit('change', page, props.pageSize)
}
function resize(size: number): void {
  if (props.disabled || !pageSizes.includes(size) || size === props.pageSize) return
  // 每页条数变化时统一回到首页，避免不同列表采用不同的跳页行为。
  emit('change', 1, size)
}
// Naive UI 默认页项使用 div；补充原生按钮，保留 Enter/空格操作与当前页读屏提示。
const renderLabel: PaginationRenderLabel = info => h('button', {
  type: 'button', class: 'pagination-page-label', disabled: props.disabled,
  'aria-label': info.type === 'page' ? `第 ${info.node} 页` : info.type === 'fast-forward' ? '向后翻页' : '向前翻页',
  'aria-current': info.type === 'page' && info.active ? 'page' : undefined
}, [info.node])
</script>

<template>
  <nav class="workspace-pagination" aria-label="表格分页">
    <span class="pagination-total" role="status">共 <strong>{{ total }}</strong> 条</span>
    <!-- 空列表仍显示总数；有数据的单页列表也显示页码，保持底部布局一致。 -->
    <NPagination v-if="total > 0" class="pagination-controls" :page="page" :page-size="pageSize"
      :page-count="pageCount" :page-slot="5" :page-sizes="pageSizes" show-size-picker
      :disabled="disabled" :select-props="{ inputProps: { 'aria-label': '每页条数' } }" :label="renderLabel" @update:page="changePage" @update:page-size="resize">
      <template #prev>
        <button class="pagination-page-label" type="button" aria-label="上一页" :disabled="disabled || page <= 1">‹</button>
      </template>
      <template #next>
        <button class="pagination-page-label" type="button" aria-label="下一页" :disabled="disabled || page >= pageCount">›</button>
      </template>
    </NPagination>
  </nav>
</template>

<style scoped>
/* 分页整体居中；恢复列宽入口由表格页脚独立定位，不挤偏页码。 */
.workspace-pagination { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 12px; color: #718399; font-size: 13px; }
.pagination-total { white-space: nowrap; }
.pagination-total strong { color: #40566e; font-weight: 600; }
.pagination-controls { justify-content: center; flex-wrap: wrap; }
:deep(.pagination-page-label) { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; cursor: inherit; }
:deep(.pagination-page-label:focus-visible) { outline: 2px solid currentColor; outline-offset: 2px; border-radius: 3px; }
:root[data-theme='dark'] .workspace-pagination { color: #9cb0c7; }
:root[data-theme='dark'] .pagination-total strong { color: #dce8f5; }
</style>
