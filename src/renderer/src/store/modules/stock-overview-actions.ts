import { watch } from 'vue'
import type { AppState } from '../state'
import { validateStockOverview } from '../../../../shared/stock-overview.ts'
import { displayError } from '../../utils/formatters.ts'

// 总览只读取一页库存，统计卡片直接使用同一次服务端查询返回的总数。
export function createStockOverviewActions(state: AppState) {
  let ticket = 0
  const allowed = (): boolean => !!window.nexora && !state.connectionLost.value
    && !!state.user.value?.permissions.includes('inventory.view')
  function invalidate(): void {
    ticket++
    state.stockOverviewResult.value = null
    state.stockOverviewLoading.value = false
    state.stockOverviewError.value = ''
  }
  watch(() => JSON.stringify([state.stockOverviewQuery.value.warehouse_id,
    state.stockOverviewQuery.value.keyword, state.stockOverviewQuery.value.category_group]), () => {
    state.stockOverviewQuery.value.page = 1
    invalidate()
  }, { flush: 'sync' })
  // 同一账号刷新 me 快照不应清空当前页；仅真实会话边界变化使响应失效。
  watch(() => JSON.stringify([state.user.value?.id, state.user.value?.permissions.join('|'),
    state.connectionLost.value, state.server.value?.id]),
    invalidate, { flush: 'sync' })
  async function queryStockOverview(page = state.stockOverviewQuery.value.page,
                                    pageSize = state.stockOverviewQuery.value.page_size): Promise<void> {
    if (!allowed()) return
    const query = state.stockOverviewQuery.value
    query.page = pageSize === query.page_size ? page : 1
    query.page_size = pageSize
    const current = ++ticket
    state.stockOverviewLoading.value = true
    state.stockOverviewError.value = ''
    try {
      const result = await window.nexora!.callApi('queryStock', { ...query })
      if (current !== ticket || !allowed()) return
      validateStockOverview(result)
      state.stockOverviewResult.value = result
      query.page = result.page
      query.page_size = result.page_size
    } catch (cause) {
      if (current !== ticket) return
      invalidate()
      state.stockOverviewError.value = displayError(cause)
    } finally {
      if (current === ticket) state.stockOverviewLoading.value = false
    }
  }
  async function resetStockOverview(): Promise<void> {
    // 一次重置全部条件并从首页查询，不影响其他页面的物料筛选。
    state.stockOverviewQuery.value = { warehouse_id: null, keyword: '', category_group: null,
      page: 1, page_size: state.stockOverviewQuery.value.page_size }
    await queryStockOverview(1)
  }
  return { queryStockOverview, resetStockOverview }
}
