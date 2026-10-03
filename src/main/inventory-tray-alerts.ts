import type { InventoryWarningEventPage } from '../shared/inventory-warning-api'
import type { InventoryWarningNotice } from '../shared/inventory-warning-notification'

interface TrayAlertDependencies {
  sessionMarker: () => number | null
  read: (beforeId?: number) => Promise<InventoryWarningEventPage>
  windowOpen: () => boolean
  notify: (notice: InventoryWarningNotice) => void
}

const MAX_PAGES = 200

// 托盘仍运行时从服务端事件补读；只在完整翻到上次游标后提交新游标。
export function createInventoryTrayAlerts(deps: TrayAlertDependencies) {
  let timer: ReturnType<typeof setInterval> | null = null
  let marker: number | null = null
  let cursor: number | null = null
  let inFlight: Promise<void> | null = null
  let lifecycle = 0
  let stopped = false

  async function readEvents(): Promise<void> {
    const active = deps.sessionMarker()
    if (active === null) { marker = null; cursor = null; return }
    if (marker !== active) { marker = active; cursor = null }
    const lastSeen = cursor
    const ticket = lifecycle
    let newest = lastSeen ?? 0
    let beforeId: number | undefined
    let outOfStock = 0
    let low = 0
    try {
      for (let pageNumber = 0; pageNumber < MAX_PAGES; pageNumber++) {
        const page = await deps.read(beforeId)
        if (ticket !== lifecycle || deps.sessionMarker() !== active) return
        if (page.warehouse_id !== null) throw new Error('库存预警事件范围不匹配')
        const events = page.events
        if (events.some((event, index) => index > 0 && event.id >= events[index - 1]!.id))
          throw new Error('库存预警事件顺序无效')
        if (events.length) newest = Math.max(newest, events[0]!.id)
        if (lastSeen === null) break
        for (const event of events) {
          if (event.id <= lastSeen) break
          if (event.status === 'out_of_stock') outOfStock++
          else low++
        }
        if (events.some(event => event.id <= lastSeen) || page.next_before_id === null) break
        if (!events.length || page.next_before_id > events[events.length - 1]!.id
          || (beforeId !== undefined && page.next_before_id >= beforeId))
          throw new Error('库存预警事件分页无效')
        beforeId = page.next_before_id
        if (pageNumber === MAX_PAGES - 1) throw new Error('库存预警事件翻页过多')
      }
      if (ticket !== lifecycle || deps.sessionMarker() !== active) return
      if (lastSeen !== null && !deps.windowOpen() && outOfStock + low > 0) {
        // 系统通知失败只影响本次送达，服务端事件仍留在历史页供核对。
        try { deps.notify({ outOfStock, low }) } catch { /* 应用内及历史记录仍可用。 */ }
      }
      cursor = newest
    } catch {
      // 读取失败不推进游标，下次继续从相同位置补读。
    }
  }

  function poll(): Promise<void> {
    if (stopped) return Promise.resolve()
    if (inFlight) return inFlight.then(() => deps.sessionMarker() !== marker ? poll() : undefined)
    inFlight = readEvents().finally(() => { inFlight = null })
    return inFlight
  }

  function start(): void {
    if (timer) return
    stopped = false
    lifecycle++
    void poll()
    timer = setInterval(() => { void poll() }, 60_000)
  }

  function stop(): void {
    if (timer) clearInterval(timer)
    timer = null
    lifecycle++
    stopped = true
    marker = null
    cursor = null
  }

  return { poll, start, stop }
}
