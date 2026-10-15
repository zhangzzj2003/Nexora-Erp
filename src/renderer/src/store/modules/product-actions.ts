import { watch } from 'vue'
import type { AppState } from '../state'
import type { Bom } from '../../../../shared/erp-api'
import type { ProductInput, ProductProfile, ProductModel } from '../../../../shared/product-api'
import { validateProductResult } from '../../../../shared/product-api.ts'
import { materialDraft, materialInput } from '../../utils/material-form.ts'
import { displayError } from '../../utils/formatters.ts'

// 分页与详情按稳定会话失效；普通 me 刷新不会清空当前条件或输入。
export function createProductActions(state: AppState) {
  let listTicket = 0, detailTicket = 0, bomTicket = 0, editTicket = 0, writeTicket = 0
  let ownedWrite: number | null = null
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const identity = (): string => JSON.stringify([state.server.value?.id, state.server.value?.fingerprint, state.user.value?.id])
  const allowed = (permission: string): boolean => !!window.nexora && !state.connectionLost.value && can(permission)
  function invalidateReads(): void {
    listTicket++; detailTicket++; bomTicket++; editTicket++
    if (ownedWrite !== null) {ownedWrite = null; state.busy.value = false}
    state.productResult.value = null; state.productModels.value = []
    state.productDetailRecord.value = null; state.productBomRecords.value = []; state.productChangeRecords.value = []
    // 机型历史和失败提示也属于当前读取会话，不能带到新账号或证书实例。
    state.productModelChanges.value = []
    state.productsError.value = ''; state.productDetailError.value = ''; state.bomDetailError.value = ''
    state.productDetailId.value = 0; state.bomDetailRecord.value = null
    state.productsLoading.value = false; state.productDetailLoading.value = false; state.bomDetailLoading.value = false
  }
  watch(identity, () => {
    invalidateReads(); state.productEditorOpen.value = false; state.productReturnToBom.value = false
    state.productForm.value = {id: 0, version: 0, mode: 'new', material_id: 0, kind: 'finished', model_id: null, configuration_name: '', can_sell: true, can_purchase: true, can_produce: true, reason: ''}
    state.productMaterialForm.value = materialDraft()
    state.bomForm.value = {product_material_id: 0, source_bom_id: null, base_quantity: '1', note: '', lines: [{component_material_id: 0, quantity: '1'}]}
    state.productModelForm.value = {id: 0, version: 0, code: '', name: '', notes: '', reason: ''}
  }, {flush: 'sync'})
  watch(() => JSON.stringify([state.user.value?.permissions.slice().sort(), state.connectionLost.value]), () => {
    invalidateReads()
    if (!can('catalog.manage')) {state.productEditorOpen.value = false; state.productReturnToBom.value = false}
  }, {flush: 'sync'})
  watch(() => JSON.stringify([state.productQuery.value.query, state.productQuery.value.kind, state.productQuery.value.model_id]), () => {
    listTicket++; state.productQuery.value.page = 1; state.productResult.value = null
  }, {flush: 'sync'})
  async function queryProducts(page = state.productQuery.value.page): Promise<void> {
    if (!allowed('inventory.view')) return
    const ticket = ++listTicket
    state.productsLoading.value = true; state.productsError.value = ''
    try {
      const [result, models] = await Promise.all([window.nexora!.callApi('queryProducts', {...state.productQuery.value, page}),
        window.nexora!.callApi('productModels', undefined)])
      if (ticket !== listTicket || !allowed('inventory.view')) return
      validateProductResult('queryProducts', result); validateProductResult('productModels', models)
      state.productResult.value = result; state.productModels.value = models
      state.productQuery.value.page = result.page
    } catch (cause) {if (ticket === listTicket) {state.productResult.value = null; state.productsError.value = displayError(cause)}}
    finally {if (ticket === listTicket) state.productsLoading.value = false}
  }
  async function openProduct(id: number): Promise<void> {
    if (!allowed('inventory.view') || state.busy.value) return
    const ticket = ++detailTicket
    state.productDetailId.value = id; state.productDetailRecord.value = null
    state.productBomRecords.value = []; state.productChangeRecords.value = []
    state.productDetailLoading.value = true; state.productDetailError.value = ''
    try {
      const [row, changes] = await Promise.all([window.nexora!.callApi('productDetail', {id}), window.nexora!.callApi('productChanges', {id})])
      if (ticket !== detailTicket || !allowed('inventory.view')) return
      validateProductResult('productDetail', row); validateProductResult('productChanges', changes)
      if (row.id !== id) throw Error('服务端返回了另一产品的资料')
      const boms = can('production.view') ? await window.nexora!.callApi('productBoms', {materialId: row.material_id}) : []
      if (ticket !== detailTicket || !allowed('inventory.view')) return
      validateProductResult('productBoms', boms)
      if (boms.some(bom => bom.product_material_id !== row.material_id)) throw Error('产品 BOM 范围不一致')
      state.productDetailRecord.value = row; state.productChangeRecords.value = changes; state.productBomRecords.value = boms
    } catch (cause) {if (ticket === detailTicket) state.productDetailError.value = displayError(cause)}
    finally {if (ticket === detailTicket) state.productDetailLoading.value = false}
  }
  function closeProduct(): void {detailTicket++; state.productDetailId.value = 0; state.productDetailLoading.value = false}
  async function startProduct(mode: 'new' | 'existing' | 'edit', id = 0, returnToBom = false, parentModelId?: number | null): Promise<void> {
    if (!allowed('catalog.manage') || state.busy.value) return
    // 同一未完成草稿再次打开直接沿用；主动切换建档方式才更换草稿。
    const same = state.productForm.value.mode === mode && state.productForm.value.id === id
    const ticket = ++editTicket
    try {
      const models = await window.nexora!.callApi('productModels', undefined)
      if (ticket !== editTicket || !allowed('catalog.manage')) return
      validateProductResult('productModels', models)
      if (parentModelId !== undefined && parentModelId !== null && !models.some(row=>row.id===parentModelId)) throw Error('所选产品系列已不存在，请刷新目录')
      state.productModels.value = models
      if (!same) {
        state.productForm.value = {id: 0, version: 0, mode, material_id: 0, kind: 'finished', model_id: null, configuration_name: '', can_sell: true, can_purchase: true, can_produce: true, reason: ''}
        state.productMaterialForm.value = materialDraft()
      }
      if (mode === 'edit' && (!same || !state.productForm.value.version)) {
        const row = await window.nexora!.callApi('productDetail', {id})
        if (ticket !== editTicket || !allowed('catalog.manage')) return
        if (row.id !== id) throw Error('服务端返回了另一产品的编辑资料')
        state.productForm.value = {id: row.id, version: row.version, mode, material_id: row.material_id,
          kind: row.kind, model_id: row.model_id, configuration_name: row.configuration_name, can_sell: row.can_sell ?? true,
          can_purchase: row.can_purchase ?? true, can_produce: row.can_produce ?? true, reason: ''}
        state.productMaterialForm.value = materialDraft(row.material)
      }
      // 左侧明确选择“新建子机型”时继承所在系列，其余字段仍保留未保存草稿。
      if (mode !== 'edit' && parentModelId !== undefined) state.productForm.value.model_id = parentModelId
      state.productReturnToBom.value = returnToBom; state.productEditorOpen.value = true
    } catch (cause) {if (ticket === editTicket) state.error.value = displayError(cause)}
  }
  async function write<T>(operation: () => Promise<T>): Promise<T | undefined> {
    if (!allowed('catalog.manage') || state.busy.value) return
    const ticket = ++writeTicket
    ownedWrite = ticket
    const epoch = editTicket
    const session = identity(), permissions = state.user.value!.permissions.slice().sort().join('|')
    state.busy.value = true; state.error.value = ''; state.notice.value = ''
    try {
      const result = await operation()
      // 写入已经发生，但跨会话的响应不能回填另一实例草稿或发起后续读取。
      if (ownedWrite !== ticket || epoch !== editTicket || identity() !== session || state.user.value?.permissions.slice().sort().join('|') !== permissions || !allowed('catalog.manage')) return
      return result
    } catch (cause) {if (ownedWrite === ticket && epoch === editTicket && identity() === session) state.error.value = displayError(cause)}
    finally {if (ownedWrite === ticket) {ownedWrite = null; state.busy.value = false}}
  }
  async function saveProduct(): Promise<ProductProfile | undefined> {
      return await write(async () => {
      const form = state.productForm.value
      const fields = {can_sell: form.can_sell, can_purchase: form.can_purchase, can_produce: form.can_produce, kind: form.kind, model_id: form.model_id, configuration_name: form.configuration_name, reason: form.reason}
      const payload: ProductInput = form.mode === 'existing' ? {...fields, material_id: form.material_id}
        : {...fields, material: materialInput(state.productMaterialForm.value, form.mode === 'edit', state.materialUnits.value)}
      const result = form.mode === 'edit'
        ? await window.nexora!.callApi('updateProduct', {...fields, id: form.id, version: form.version,
          material: materialInput(state.productMaterialForm.value, true, state.materialUnits.value)})
        : await window.nexora!.callApi('createProduct', payload)
      return result
    }).then(async row => {
      if (!row) return
      const session = identity()
      validateProductResult('productDetail', row)
      // 快捷创建只带回产出物料，已经填写的 BOM 基准数和组件逐行保留。
      if (state.productReturnToBom.value) state.bomForm.value.product_material_id = row.material_id
      state.materials.value = [...state.materials.value.filter(item => item.id !== row.material_id), row.material]
      state.productEditorOpen.value = false; state.productReturnToBom.value = false
      state.productForm.value = {id: 0, version: 0, mode: 'new', material_id: 0, kind: 'finished', model_id: null, configuration_name: '', can_sell: true, can_purchase: true, can_produce: true, reason: ''}
      state.productMaterialForm.value = materialDraft(); state.notice.value = '产品档案已保存。'
      await queryProducts()
      if (state.productDetailId.value === row.id) await openProduct(row.id)
      // 导航仅接收当前会话保存的记录，查询期间切换账号不能选中旧机型。
      if (identity() === session && allowed('catalog.manage')) return row
    }).catch(cause => {state.error.value = displayError(cause); return undefined})
  }
  async function saveProductModel(): Promise<ProductModel | undefined> {
    const row = await write(async () => {
      const {id, ...payload} = state.productModelForm.value
      return id ? window.nexora!.callApi('updateProductModel', {...payload, id})
        : window.nexora!.callApi('createProductModel', payload)
    })
    if (!row) return
    const session = identity()
    validateProductResult('productModelDetail', row)
    state.productModelForm.value = {id: 0, version: 0, code: '', name: '', notes: '', reason: ''}
    state.productModelChanges.value = []
    state.notice.value = '产品系列已保存。'; await queryProducts()
    if (identity() === session && allowed('catalog.manage')) return row
  }
  async function editProductModel(id: number): Promise<void> {
    if (!allowed('catalog.manage') || state.busy.value) return
    const ticket = ++editTicket
    try {
      const [row, changes] = await Promise.all([window.nexora!.callApi('productModelDetail', {id}), window.nexora!.callApi('productModelChanges', {id})])
      if (ticket !== editTicket || !allowed('catalog.manage')) return
      if (row.id !== id) throw Error('服务端返回了另一产品系列的资料')
      state.productModelForm.value = {...row, reason: ''}; state.productModelChanges.value = changes
    } catch (cause) {if (ticket === editTicket) state.error.value = displayError(cause)}
  }
  function prepareProductBom(materialId: number, source?: Bom): boolean {
    if (!allowed('bom.create') || state.busy.value || source?.status === 'cancelled') return false
    // 再次打开同一产品与同一来源时沿用未保存草稿；切换意图才复制新行。
    if (state.bomForm.value.product_material_id === materialId && (state.bomForm.value.source_bom_id ?? null) === (source?.id ?? null)) return true
    state.bomForm.value = source ? {product_material_id: materialId, base_quantity: source.base_quantity,
      note: '', source_bom_id: source.id, lines: source.lines.map(line => ({component_material_id: line.component_material_id, quantity: line.quantity, component_bom_id: line.component_bom_id ?? null}))}
      : {product_material_id: materialId, base_quantity: '1', note: '', source_bom_id: null, lines: [{component_material_id: 0, quantity: '1'}]}
    return true
  }
  async function openBomDetail(bomId: number): Promise<void> {
    if (!allowed('production.view') || state.busy.value) return
    const ticket = ++bomTicket
    state.bomDetailLoading.value = true; state.bomDetailError.value = ''; state.bomDetailRecord.value = null
    try {
      const row = await window.nexora!.callApi('bomDetail', {bomId})
      if (ticket === bomTicket && allowed('production.view')) {
        validateProductResult('bomDetail', row)
        if (row.id !== bomId) throw Error('服务端返回了另一 BOM 的版本')
        state.bomDetailRecord.value = row
      }
    } catch (cause) {if (ticket === bomTicket) state.bomDetailError.value = displayError(cause)}
    finally {if (ticket === bomTicket) state.bomDetailLoading.value = false}
  }
  function closeBomDetail(): void {bomTicket++; state.bomDetailRecord.value = null; state.bomDetailLoading.value = false; state.bomDetailError.value = ''}
  return {queryProducts, openProduct, closeProduct, startProduct, saveProduct, saveProductModel, editProductModel,
    prepareProductBom, openBomDetail, closeBomDetail}
}
