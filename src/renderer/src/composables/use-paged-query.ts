import { onScopeDispose, ref, shallowRef } from 'vue'
import type { PageQuery, PageResult } from '../../../shared/erp-api'

// 每个页面独立保存查询状态；序号保证慢请求不会覆盖更新的搜索结果。
export function usePagedQuery<T>(request: (query: PageQuery) => Promise<PageResult<T>>, accept?: (result: PageResult<T> & { metadata?: Record<string, unknown> | null }) => void) {
  const rows = shallowRef<T[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const loading = ref(false)
  const error = ref('')
  let version = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let keyword = ''

  async function load(targetPage = page.value, targetSize = pageSize.value): Promise<void> {
    clearTimeout(timer)
    const current = ++version
    loading.value = true
    error.value = ''
    try {
      const result = await request({ query: keyword, page: targetPage, page_size: targetSize })
      if (current !== version) return
      accept?.(result)
      rows.value = result.items
      total.value = result.total
      page.value = result.page
      pageSize.value = result.page_size
    } catch (reason) {
      if (current !== version) return
      rows.value = []
      error.value = reason instanceof Error ? reason.message : '查询失败，请重试。'
    } finally {
      if (current === version) loading.value = false
    }
  }

  function search(value: string): void {
    // 输入变化立即使旧响应失效，稍后再发请求，避免逐字请求与结果闪回。
    rows.value = []
    total.value = 0
    keyword = value.trim()
    ++version
    clearTimeout(timer)
    page.value = 1
    loading.value = true
    error.value = ''
    timer = setTimeout(() => { void load(1) }, 250)
  }

  onScopeDispose(() => { ++version; clearTimeout(timer) })
  return { rows, total, page, pageSize, loading, error, load, search }
}
