import { watch, onScopeDispose, getCurrentScope } from 'vue'
import type { AppState } from '../state'
import { materialSupplyBody, validateMaterialSupply } from '../../../../shared/material-supply-api.ts'
import { displayError } from '../../utils/formatters.ts'

export function createMaterialSupplyActions(state: AppState) {
  const queued = new Map<number, Array<(loaded: boolean) => void>>()
  const running = new Set<number>()
  let scheduled = false
  const subscriptions = new Map<number, number>()
  let timer: ReturnType<typeof setInterval> | null = null
  function stopTimer(): void { if (timer) clearInterval(timer); timer = null }
  if (getCurrentScope()) onScopeDispose(stopTimer)
  const available = () => !!window.nexora && !!state.user.value && !state.connectionLost.value
  function invalidateMaterialSupply(): void {
    // 同步清空账号、实例和权限边界；迟到响应不能把旧账号的数据重新填回。
    state.materialSupplyEpoch.value++
    state.materialSupplyRows.value = {}; state.materialSupplyLoading.value = {}; state.materialSupplyErrors.value = {}
    for (const callbacks of queued.values()) callbacks.forEach(done => done(false))
    queued.clear(); running.clear()
  }
  watch(() => `${state.user.value?.id}:${state.user.value?.permissions.join('|')}:${state.server.value?.id}:${state.server.value?.fingerprint}:${state.connectionLost.value}`,
    invalidateMaterialSupply, { flush: 'sync' })
  // 本地业务快照更新后重新读取当前供需，不让入库后的旧待入库数继续展示。
  watch([state.stock, state.receipts, state.purchaseOrders, state.purchaseRequests, state.goodsReceipts, state.mrpPlans],
    invalidateMaterialSupply, { flush: 'sync' })

  async function drain(): Promise<void> {
    scheduled = false
    const ticket = state.materialSupplyEpoch.value
    const entries = [...queued.entries()]; queued.clear()
    for (let offset = 0; offset < entries.length; offset += 100) {
      const batch = entries.slice(offset, offset + 100), ids = batch.map(([id]) => id)
      let loaded = false
      try {
        if (ticket !== state.materialSupplyEpoch.value || !available()) continue
        const result = await window.nexora!.callApi('materialSupply', { material_ids: ids })
        validateMaterialSupply(result, ids)
        if (ticket !== state.materialSupplyEpoch.value || !available()) continue
        for (const row of result.rows) state.materialSupplyRows.value[row.material_id] = { row, generatedAt: result.generated_at }
        loaded = true
      } catch (error) {
        if (ticket === state.materialSupplyEpoch.value) for (const id of ids) state.materialSupplyErrors.value[id] = displayError(error)
      } finally {
        for (const [id, callbacks] of batch) {
          if (ticket === state.materialSupplyEpoch.value) { running.delete(id); state.materialSupplyLoading.value[id] = false }
          callbacks.forEach(done => done(loaded))
        }
      }
    }
  }

  function loadMaterialSupply(id: number, refresh = false): Promise<boolean> {
    materialSupplyBody({ material_ids: [id] })
    if (!available()) return Promise.resolve(false)
    if (running.has(id)) return Promise.resolve(false)
    const cached = state.materialSupplyRows.value[id]
    if (!refresh && cached && Date.now() - Date.parse(cached.generatedAt) < 15000) return Promise.resolve(true)
    delete state.materialSupplyRows.value[id]; delete state.materialSupplyErrors.value[id]
    state.materialSupplyLoading.value[id] = true; running.add(id)
    // 同一轮渲染的所有行先合并再分批请求，重复物料不会产生逐行网络请求。
    const completion = new Promise<boolean>(resolve => queued.set(id, [resolve]))
    if (!scheduled) { scheduled = true; void Promise.resolve().then(drain) }
    return completion
  }
  function subscribeMaterialSupply(id: number): () => void {
    subscriptions.set(id, (subscriptions.get(id) ?? 0) + 1)
    if (!timer) timer = setInterval(() => {
      // 所有可见行共用一个刷新时钟，在同一轮收集合并，隐藏或关闭后释放订阅。
      if (available()) for (const materialId of subscriptions.keys()) void loadMaterialSupply(materialId, true)
    }, 15000)
    void loadMaterialSupply(id)
    return () => {
      const count = (subscriptions.get(id) ?? 1) - 1
      if (count) subscriptions.set(id, count); else subscriptions.delete(id)
      if (!subscriptions.size) stopTimer()
    }
  }
  return { loadMaterialSupply, invalidateMaterialSupply, subscribeMaterialSupply }
}
