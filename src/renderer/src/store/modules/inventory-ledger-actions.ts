import { watch } from 'vue'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

// 台账读取不走业务写操作，避免每次翻页都刷新全部业务资料。
export function createInventoryLedgerActions(state: AppState) {
  let ticket = 0
  const allowed = (): boolean => !!window.nexora && !state.connectionLost.value
    && !!state.user.value?.permissions.includes('inventory.view')
  function invalidate(): void {
    ticket++
    state.ledgerLoading.value = false
    state.ledgerError.value = ''
    state.ledgerResult.value = { groups: [], rows: [], total: 0,
      page: state.ledgerQuery.value.page, page_size: state.ledgerQuery.value.page_size }
  }
  // 筛选变更立即回到首页并清除旧结果，不能把旧汇总当作新筛选结果。
  watch(() => {
    const { warehouse_id, material_id, from_date, to_date, source_type } = state.ledgerQuery.value
    return [warehouse_id, material_id, from_date, to_date, source_type]
  }, () => { state.ledgerQuery.value.page = 1; invalidate() }, { flush: 'sync' })
  // 同一账号刷新 me 快照不应清空当前页；仅真实会话边界变化使响应失效。
  watch(() => JSON.stringify([state.user.value?.id, state.user.value?.permissions.join('|'),
    state.connectionLost.value, state.server.value?.id]),
    invalidate, { flush: 'sync' })

  async function queryLedger(page = 1, pageSize = state.ledgerQuery.value.page_size): Promise<void> {
    if (!allowed()) return
    // 每页条数变化统一回首页；失败后保留目标页，供原页重试。
    state.ledgerQuery.value.page = pageSize === state.ledgerQuery.value.page_size ? page : 1
    state.ledgerQuery.value.page_size = pageSize
    const current = ++ticket
    state.ledgerLoading.value = true
    state.ledgerError.value = ''
    const query = { ...state.ledgerQuery.value,
      from_date: state.ledgerQuery.value.from_date || null,
      to_date: state.ledgerQuery.value.to_date || null }
    try {
      const result = await window.nexora!.callApi('inventoryLedger', query)
      if (current !== ticket || !allowed()) return
      // 老服务端返回全量结果时明确提示升级，避免界面误装成已经分页。
      if (!Number.isInteger(result.total) || !Number.isInteger(result.page)
          || !Number.isInteger(result.page_size)) throw Error('服务端尚未支持库存台账分页，请升级服务端后重试。')
      state.ledgerResult.value = result
      state.ledgerQuery.value.page = result.page
      state.ledgerQuery.value.page_size = result.page_size
    } catch (cause) {
      if (current !== ticket) return
      invalidate()
      state.ledgerError.value = displayError(cause)
    } finally {
      if (current === ticket) state.ledgerLoading.value = false
    }
  }
  return { queryLedger }
}
