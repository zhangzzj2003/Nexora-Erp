import { watch } from 'vue'
import type { InventoryWarningStatus } from '../../../../shared/inventory-warning-api'
import type { AppState } from '../state'

const attention = (status: InventoryWarningStatus): boolean =>
  status === 'low' || status === 'out_of_stock'

// 提醒只在当前已登录窗口内轮询；账号、实例或连接变化时丢弃旧快照。
export function createInventoryWarningAlerts(state: AppState) {
  let timer: ReturnType<typeof setInterval> | null = null
  let generation = 0
  let reading = false
  let previous: Map<string, InventoryWarningStatus> | null = null
  let sequence = 0
  const context = () => {
    const account = state.user.value
    if (state.screen.value !== 'app' || state.connectionLost.value || !account?.permissions.includes('inventory.view'))
      return ''
    const server = state.server.value
    return `${server?.id ?? ''}:${server?.fingerprint ?? ''}:${account.id}:${account.permissions.join('|')}`
  }
  watch(context, () => {
    generation++
    previous = null
    state.warningAlert.value = null
    if (timer) void poll()
  }, { flush: 'sync' })

  async function poll(): Promise<void> {
    const session = context()
    if (!session || !window.nexora || reading) return
    const ticket = generation
    reading = true
    try {
      const result = await window.nexora.callApi('inventoryWarnings', undefined)
      if (ticket !== generation || session !== context() || result.warehouse_id !== null) return
      const current = new Map<string, InventoryWarningStatus>()
      const changed: typeof result.rows = []
      for (const row of result.rows) {
        const key = `${row.warehouse_id}:${row.material_id}`
        current.set(key, row.status)
        if (attention(row.status) && (!previous || !attention(previous.get(key) ?? 'normal') ||
          (previous.get(key) === 'low' && row.status === 'out_of_stock'))) changed.push(row)
      }
      previous = current
      if (changed.length) {
        const missing = changed.filter(row => row.status === 'out_of_stock').length
        const low = changed.length - missing
        const count = [missing && `缺货 ${missing} 项`, low && `低库存 ${low} 项`].filter(Boolean).join('、')
        const examples = changed.slice(0, 2).map(row => `${row.warehouse_code} / ${row.sku}`).join('，')
        state.warningAlert.value = { id: ++sequence, content: `库存预警：${count}（${examples}${changed.length > 2 ? ' 等' : ''}）。请到库存预警页核对。` }
        // 系统通知仅在应用窗口失焦时由主进程显示；失败不影响应用内提醒。
        void window.nexora.notifyInventoryWarning({ outOfStock: missing, low }).catch(() => {})
      }
    } catch {
      // 读取失败不把旧状态当作库存恢复，也不以失效数据弹出提醒。
    } finally {
      reading = false
      // 旧账号或旧实例读取刚结束时，立刻补读新会话，不等待下一个周期。
      if (ticket !== generation && timer) void poll()
    }
  }

  function start(): void {
    if (timer) return
    void poll()
    timer = setInterval(() => { void poll() }, 60_000)
  }

  function stop(): void {
    if (timer) clearInterval(timer)
    timer = null
    generation++
    previous = null
    state.warningAlert.value = null
  }

  return { poll, start, stop }
}
