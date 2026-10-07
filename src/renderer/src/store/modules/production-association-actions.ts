import { watch } from 'vue'
import { productionAssociationInput, validateProductionAssociations } from '../../../../shared/production-association-api.ts'
import type { ProductionAssociationTarget } from '../../../../shared/production-association-api'
import type { AppState } from '../state'

// 只读关联状态归 Pinia 管理；切服、账号或权限变化立即清除旧业务证据。
export function createProductionAssociationActions(state: AppState) {
  let owner = 0, reads = 0
  const available = () => !!window.nexora && !state.connectionLost.value && !!state.user.value?.permissions.includes('production.view')
  watch(() => `${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.permissions.join('|')}`,
    () => {owner++; closeProductionAssociations()}, {flush: 'sync'})
  function closeProductionAssociations(): void {
    reads++; state.productionAssociationTarget.value = null; state.productionAssociationRecord.value = null
    state.productionAssociationLoading.value = false; state.productionAssociationError.value = ''
  }
  async function loadProductionAssociations(includeReferences = false): Promise<boolean> {
    const target = state.productionAssociationTarget.value
    if (!target || !available()) return false
    const ticket = ++reads, session = owner
    state.productionAssociationLoading.value = true; state.productionAssociationRecord.value = null; state.productionAssociationError.value = ''
    try {
      const record = await window.nexora!.callApi('productionAssociations', {...target, include_references: includeReferences})
      if (ticket !== reads || session !== owner || !available()) return false
      validateProductionAssociations(record)
      if (record.target.kind !== target.kind || record.target.id !== target.id) throw Error('生产关联结果与当前单据不一致。')
      state.productionAssociationRecord.value = record
      return true
    } catch (error) {
      if (ticket === reads && session === owner) state.productionAssociationError.value = error instanceof Error ? error.message : '生产关联读取失败，请重试。'
      return false
    } finally {if (ticket === reads && session === owner) state.productionAssociationLoading.value = false}
  }
  async function openProductionAssociations(target: ProductionAssociationTarget): Promise<boolean> {
    if (!available() || state.busy.value) return false
    const input = productionAssociationInput({...target, include_references: false})
    state.productionAssociationTarget.value = {kind: input.kind, id: input.id}
    return loadProductionAssociations()
  }
  return {openProductionAssociations, closeProductionAssociations, loadProductionAssociations}
}
