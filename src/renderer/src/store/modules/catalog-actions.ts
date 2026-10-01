import type { Material, MaterialInput, Supplier } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { displayError } from '../../utils/formatters.ts'

// 基础资料操作独立维护；写入后由统一入口刷新服务端快照。
export function createCatalogActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const { materialForm, supplierForm } = state

  async function loadMaterial(id: number): Promise<Material | undefined> {
    if (!window.nexora || !state.user.value || state.busy.value) return undefined
    if (state.connectionLost.value) {
      state.error.value = '服务端连接已中断，恢复连接后才能加载物料。'
      return undefined
    }
    const user = state.user.value
    const server = state.server.value
    state.busy.value = true
    state.error.value = ''
    try {
      // 单条查询不触发全业务刷新；切换账号、实例或断线后的迟到结果不打开编辑器。
      const latest = await window.nexora.callApi('materialDetail', { id })
      if (state.user.value !== user || state.server.value !== server || state.connectionLost.value) return undefined
      state.materials.value = state.materials.value.map(item => item.id === id ? latest : item)
      return latest
    } catch (cause) {
      if (state.user.value === user && state.server.value === server) state.error.value = displayError(cause)
      return undefined
    } finally {
      state.busy.value = false
    }
  }

  async function createMaterial(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      // Vue 的响应式代理不能通过 Electron IPC，发送前只取普通字段。
      await window.nexora!.callApi('createMaterial', { ...materialForm.value })
      materialForm.value = { sku: '', name: '', unit: '件' }
    }, '物料已保存。')
  }

  async function createSupplier(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createSupplier', {
        name: supplierForm.value.name
      })
      supplierForm.value = { name: '' }
    }, '供应商已保存。')
  }

  async function saveMaterial(data: MaterialInput, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      // 编辑必须携带快照版本；失败时保留草稿，重新打开可读取服务端最新版本。
      if (id) {
        if (!data.version) throw new Error('请重新打开物料编辑窗口以读取最新版本。')
        await window.nexora!.callApi('updateMaterial', { ...data, version: data.version, id })
      }
      else await window.nexora!.callApi('createMaterial', { ...data })
      saved = true
    }, '物料已保存。')
    return saved
  }

  async function deleteMaterial(id: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('deleteMaterial', { id }), '物料已删除。')
  }

  async function saveSupplier(data: Omit<Supplier, 'id'>, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      if (id) await window.nexora!.callApi('updateSupplier', { ...data, id })
      else await window.nexora!.callApi('createSupplier', { ...data })
      saved = true
    }, '供应商已保存。')
    return saved
  }

  async function deleteSupplier(id: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('deleteSupplier', { id }), '供应商已删除。')
  }

  async function setSupplierMaterial(supplierId: number, materialId: number, bound: boolean): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi(bound ? 'bindSupplierMaterial' : 'unbindSupplierMaterial', {
      supplierId, materialId
    }), bound ? '物料已绑定。' : '已解除物料绑定。')
  }

  return { loadMaterial, createMaterial, createSupplier, saveMaterial, deleteMaterial, saveSupplier, deleteSupplier, setSupplierMaterial }
}
