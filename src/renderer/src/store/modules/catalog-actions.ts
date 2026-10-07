import type { Material, MaterialInput, SupplierInput } from '../../../../shared/erp-api'
import type { AppState } from '../state'
import { supplierBody } from '../../../../shared/supplier-api.ts'
import { materialUnitBody } from '../../../../shared/material-unit-api.ts'
import type { MaterialUnitInput } from '../../../../shared/material-unit-api'
import { displayError } from '../../utils/formatters.ts'
import { materialCategoryBody, materialCategoryRevision, materialSpecFieldBody } from '../../../../shared/material-category-validation.ts'
import type { MaterialCategoryInput, MaterialCategoryRevision, MaterialSpecFieldInput } from '../../../../shared/material-api'

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
      const latest = await window.nexora.callApi('materialDetail', { id, include_suppliers: true })
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

  async function saveSupplier(data: SupplierInput, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      if (id) {
        if (!data.version || !data.reason?.trim()) throw new Error('请重新读取供应商版本并填写修改原因。')
        await window.nexora!.callApi('updateSupplier', { ...supplierBody(data, true), name: data.name, version: data.version, reason: data.reason, id })
      } else await window.nexora!.callApi('createSupplier', { ...supplierBody(data, false), name: data.name })
      saved = true
    }, '供应商已保存。')
    return saved
  }

  async function deleteSupplier(id: number, version: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('deleteSupplier', { id, version }), '供应商已删除。')
  }

  async function setSupplierMaterial(supplierId: number, materialId: number, bound: boolean): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi(bound ? 'bindSupplierMaterial' : 'unbindSupplierMaterial', {
      supplierId, materialId
    }), bound ? '物料已绑定。' : '已解除物料绑定。')
  }

  async function saveMaterialUnit(data: MaterialUnitInput, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      // 页面不持有跨页目录，写成功后统一刷新单位和物料快照。
      if (id) {
        if (!data.version || !data.reason?.trim()) throw new Error('请重新读取单位版本并填写修改原因。')
        await window.nexora!.callApi('updateMaterialUnit', {
          ...materialUnitBody(data, true), name: data.name, enabled: data.enabled, notes: data.notes,
          id, version: data.version, reason: data.reason
        })
      } else await window.nexora!.callApi('createMaterialUnit', {name: data.name, enabled: data.enabled, notes: data.notes})
      saved = true
    }, '单位已保存。')
    return saved
  }

  async function reloadMaterialCategories(): Promise<boolean> {
    if (!window.nexora || !state.user.value || state.busy.value || state.connectionLost.value) return false
    const user = state.user.value, server = state.server.value
    state.busy.value = true
    try {
      const rows = await window.nexora.callApi('materialCategories', undefined)
      if (state.user.value !== user || state.server.value !== server || state.connectionLost.value) return false
      state.materialCategories.value = rows
      return true
    } catch (cause) {state.error.value = displayError(cause); return false}
    finally {state.busy.value = false}
  }

  async function saveMaterialCategory(data: MaterialCategoryInput, editing: boolean): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      const body = materialCategoryBody(data, editing) as unknown as MaterialCategoryInput & {version: number; reason: string}
      if (editing) await window.nexora!.callApi('updateMaterialCategory', body)
      else await window.nexora!.callApi('createMaterialCategory', body)
      saved = true
    }, '物料类别已保存。')
    return saved
  }
  async function saveMaterialSpecField(data: MaterialSpecFieldInput & {code: string; field_id?: number}): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      // 选项经过白名单复制，响应式数组不会直接发送到 Electron。
      const body = {...materialSpecFieldBody(data), code: data.code} as unknown as MaterialSpecFieldInput & {code: string}
      if (data.field_id) await window.nexora!.callApi('updateMaterialSpecField', {...body, field_id:data.field_id})
      else await window.nexora!.callApi('createMaterialSpecField', body)
      saved = true
    }, '规格字段已保存。')
    return saved
  }
  async function removeMaterialCategory(data: MaterialCategoryRevision, field_id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      const body = {code:data.code, ...materialCategoryRevision(data)}
      if (field_id) await window.nexora!.callApi('deleteMaterialSpecField', {...body, field_id})
      else await window.nexora!.callApi('deleteMaterialCategory', body)
      saved = true
    }, field_id ? '未使用规格字段已移除。' : '未使用类别已移除。')
    return saved
  }
  async function loadMaterialCategoryChanges(code: string): Promise<boolean> {
    if (!window.nexora || !state.user.value || state.busy.value || state.connectionLost.value) return false
    const user = state.user.value, server = state.server.value
    state.busy.value = true
    try {
      const rows = await window.nexora.callApi('materialCategoryChanges', {code})
      if (state.user.value !== user || state.server.value !== server || state.connectionLost.value) return false
      state.materialCategoryChanges.value = rows
      return true
    } catch (cause) {state.error.value = displayError(cause); return false}
    finally {state.busy.value = false}
  }

  return { loadMaterial, createMaterial, createSupplier, saveMaterial, deleteMaterial, saveSupplier, deleteSupplier, setSupplierMaterial, saveMaterialUnit,
    reloadMaterialCategories, saveMaterialCategory, saveMaterialSpecField, removeMaterialCategory, loadMaterialCategoryChanges }
}
