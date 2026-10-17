import { watch } from 'vue'
import type { AppState } from '../state'
import type { Bom } from '../../../../shared/erp-api'
import type { ProductInput, ProductProfile, ProductModel, ProductLifecycleAction, ProductQuery, ProductPage } from '../../../../shared/product-api'
import { validateProductResult } from '../../../../shared/product-api.ts'
import { materialDraft, materialInput } from '../../utils/material-form.ts'
import { displayError } from '../../utils/formatters.ts'

// 分页与详情按稳定会话失效；普通 me 刷新不会清空当前条件或输入。
export function createProductActions(state: AppState) {
  let listTicket = 0, moreTicket = 0, detailTicket = 0, changesTicket = 0, bomTicket = 0, editTicket = 0, writeTicket = 0
  let loadedScope: string | null = null
  let changesLoadedFor = 0
  let ownedWrite: number | null = null
  const can = (permission: string): boolean => state.user.value?.permissions.includes(permission) ?? false
  const identity = (): string => JSON.stringify([state.server.value?.id, state.server.value?.fingerprint, state.user.value?.id])
  const allowed = (permission: string): boolean => !!window.nexora && !state.connectionLost.value && can(permission)
  const queryScope = (query: ProductQuery = state.productQuery.value): string =>
    JSON.stringify([query.query, query.kind, query.model_id, query.page_size])
  function cancelMore(): void {
    // 追加请求属于旧目录快照；刷新或换筛选时不能回填，也不能让旧 finally 清掉新请求的状态。
    moreTicket++; state.productsLoadingMore.value = false; state.productsMoreError.value = ''
  }
  function invalidateProductChanges(): void {
    // 同编号重开也是新的读取意图，旧审计的成功、失败和 finally 都不能回填。
    changesTicket++; changesLoadedFor = 0
    state.productChangeRecords.value = []
    state.productChangesLoading.value = false; state.productChangesError.value = ''
  }
  function validatePage(result: ProductPage, query: ProductQuery, append = false): void {
    validateProductResult('queryProducts', result)
    // 普通刷新允许服务端因总数缩小而回退页码；追加必须命中所请求的下一页。
    if (result.page_size !== query.page_size || (append ? result.page !== query.page : result.page > query.page))
      throw Error('产品分页范围已变化，请刷新目录后重试')
    if (result.items.some(row => (query.model_id !== null && row.model_id !== query.model_id)
      || (query.kind !== null && row.kind !== query.kind))) throw Error('产品筛选范围不一致，请刷新目录后重试')
  }
  function invalidateReads(): void {
    listTicket++; detailTicket++; bomTicket++; editTicket++
    invalidateProductChanges()
    cancelMore(); loadedScope = null
    if (ownedWrite !== null) {ownedWrite = null; state.busy.value = false}
    state.productResult.value = null; state.productDirectoryRows.value = []; state.productModels.value = []
    state.productDetailRecord.value = null; state.productBomRecords.value = []
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
  watch(() => queryScope(), () => {
    listTicket++; state.productQuery.value.page = 1; state.productResult.value = null; state.productDirectoryRows.value = []
    cancelMore(); loadedScope = null; state.productsLoading.value = false; state.productsError.value = ''
  }, {flush: 'sync'})
  async function queryProducts(page = 1): Promise<void> {
    if (!allowed('inventory.view')) return
    const ticket = ++listTicket
    const query = {...state.productQuery.value, page}, scope = queryScope(query)
    const ownsRead = (): boolean => ticket === listTicket && scope === queryScope() && allowed('inventory.view')
    cancelMore(); loadedScope = null
    state.productsLoading.value = true; state.productsError.value = ''
    try {
      const [result, models] = await Promise.all([window.nexora!.callApi('queryProducts', query),
        window.nexora!.callApi('productModels', undefined)])
      if (!ownsRead()) return
      validatePage(result, query); validateProductResult('productModels', models)
      // 同步观察者可能在任一快照更新时切换账号；每次写入后重核会话，不能回填剩余旧资料。
      state.productResult.value = result
      if (!ownsRead()) return
      state.productDirectoryRows.value = result.items
      if (!ownsRead()) return
      state.productModels.value = models
      if (!ownsRead()) return
      state.productQuery.value.page = result.page
      if (ownsRead()) loadedScope = scope
    } catch (cause) {if (ticket === listTicket) {state.productResult.value = null; state.productDirectoryRows.value = []; state.productsError.value = displayError(cause)}}
    finally {if (ticket === listTicket) state.productsLoading.value = false}
  }
  async function loadMoreProducts(): Promise<void> {
    const current = state.productResult.value, rows = state.productDirectoryRows.value, scope = queryScope()
    if (!allowed('inventory.view') || state.busy.value || state.productsLoading.value || state.productsLoadingMore.value
      || !current || loadedScope !== scope || rows.length >= current.total
      || current.page >= Math.ceil(current.total / current.page_size)) return
    const ticket = ++moreTicket, generation = listTicket
    const query = {...state.productQuery.value, page: current.page + 1, page_size: current.page_size}
    const sameScope = (): boolean => ticket === moreTicket && generation === listTicket && scope === queryScope() && allowed('inventory.view')
    const ownsRequest = (): boolean => sameScope() && state.productResult.value === current && state.productDirectoryRows.value === rows
    state.productsLoadingMore.value = true; state.productsMoreError.value = ''
    try {
      const result = await window.nexora!.callApi('queryProducts', query)
      if (!ownsRequest()) return
      validatePage(result, query, true)
      const byId = new Map(rows.map(row => [row.id, row]))
      const materialIds = new Map(rows.map(row => [row.material_id, row.id]))
      const added: ProductProfile[] = []
      for (const row of result.items) {
        const previous = byId.get(row.id), owner = materialIds.get(row.material_id)
        // 并发新增可能让相邻页重叠，同一身份仅展示一次；不同产品不能争用物料或更换物料身份。
        if ((previous && previous.material_id !== row.material_id) || (owner !== undefined && owner !== row.id))
          throw Error('产品与已加载物料身份不一致，请刷新目录后重试')
        if (!previous) added.push(row)
      }
      const items = [...rows, ...added]
      if (!result.items.length || items.length > result.total) throw Error('产品分页范围已变化，请刷新目录后重试')
      // 只追加目录节点，不触碰详情、BOM 或展开状态，保留用户正在查看的子机型。
      state.productResult.value = result
      if (!sameScope()) return
      state.productDirectoryRows.value = items
      if (sameScope()) state.productQuery.value.page = result.page
    } catch (cause) {if (ownsRequest()) state.productsMoreError.value = displayError(cause)}
    finally {if (ticket === moreTicket) state.productsLoadingMore.value = false}
  }
  async function openProduct(id: number): Promise<void> {
    if (!allowed('inventory.view') || state.busy.value) return
    const ticket = ++detailTicket
    invalidateProductChanges()
    state.productDetailId.value = id; state.productDetailRecord.value = null
    state.productBomRecords.value = []
    state.productDetailLoading.value = true; state.productDetailError.value = ''
    try {
      // BOM 首屏只依赖产品身份，不等待尚未打开的产品审计历史。
      const row = await window.nexora!.callApi('productDetail', {id})
      if (ticket !== detailTicket || !allowed('inventory.view')) return
      validateProductResult('productDetail', row)
      if (row.id !== id) throw Error('服务端返回了另一产品的资料')
      const boms = can('production.view') ? await window.nexora!.callApi('productBoms', {materialId: row.material_id}) : []
      if (ticket !== detailTicket || !allowed('inventory.view')) return
      validateProductResult('productBoms', boms)
      if (boms.some(bom => bom.product_material_id !== row.material_id)) throw Error('产品 BOM 范围不一致')
      state.productDetailRecord.value = row; state.productBomRecords.value = boms
    } catch (cause) {if (ticket === detailTicket) state.productDetailError.value = displayError(cause)}
    finally {if (ticket === detailTicket) state.productDetailLoading.value = false}
  }
  async function loadProductChanges(force = false): Promise<void> {
    const id = state.productDetailId.value, row = state.productDetailRecord.value
    if (!allowed('inventory.view') || !id || row?.id !== id || state.productDetailLoading.value
      || state.productDetailError.value || state.productChangesLoading.value || (!force && changesLoadedFor === id)) return
    const ticket = ++changesTicket, epoch = detailTicket, session = identity()
    const permissions = state.user.value!.permissions.slice().sort().join('|')
    const ownsRead = (): boolean => ticket === changesTicket && epoch === detailTicket && identity() === session
      && state.user.value?.permissions.slice().sort().join('|') === permissions && allowed('inventory.view')
      && state.productDetailId.value === id && state.productDetailRecord.value?.id === id
      && !state.productDetailLoading.value && !state.productDetailError.value
    state.productChangesError.value = ''
    if (!ownsRead()) return
    state.productChangesLoading.value = true
    try {
      // 同步观察者可能在显示加载状态时切换账号，发出请求前仍须核对所属意图。
      if (!ownsRead()) return
      const changes = await window.nexora!.callApi('productChanges', {id})
      if (!ownsRead()) return
      validateProductResult('productChanges', changes)
      if (changes.some(change => change.after.id !== id || (change.before !== null && change.before.id !== id)))
        throw Error('服务端返回了另一产品的变更记录')
      // 单独记录成功身份，让空历史也能幂等；重新打开产品时会一并失效。
      changesLoadedFor = id
      state.productChangeRecords.value = changes
    } catch (cause) {if (ownsRead()) state.productChangesError.value = displayError(cause)}
    finally {if (ownsRead()) state.productChangesLoading.value = false}
  }
  function closeProduct(): void {
    detailTicket++; invalidateProductChanges()
    state.productDetailId.value = 0; state.productDetailLoading.value = false
  }
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
        : {...fields, material: materialInput(state.productMaterialForm.value, form.mode === 'edit', state.materialUnits.value, 'product')}
      const result = form.mode === 'edit'
        ? await window.nexora!.callApi('updateProduct', {...fields, id: form.id, version: form.version,
          material: materialInput(state.productMaterialForm.value, true, state.materialUnits.value, 'product')})
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
    const session=identity(), epoch=editTicket
    const ownsSave=():boolean => session===identity() && epoch===editTicket && allowed('catalog.manage')
    const row = await write(async () => {
      const {id, ...payload} = state.productModelForm.value
      return id ? window.nexora!.callApi('updateProductModel', {...payload, id})
        : window.nexora!.callApi('createProductModel', payload)
    })
    if (!row || !ownsSave()) return
    validateProductResult('productModelDetail', row)
    state.notice.value = '产品系列已保存。'; await queryProducts()
    // 刷新目录期间若用户换了编辑目标，不清空新草稿，也不返回旧回执去关闭新窗口。
    if (!ownsSave()) return
    state.productModelForm.value = {id: 0, version: 0, code: '', name: '', notes: '', reason: ''}
    if (!ownsSave()) return
    state.productModelChanges.value = []
    if (ownsSave()) return row
  }
  async function deleteProductModel(model: ProductModel, reason: string): Promise<boolean> {
    // busy 解除时同步监听可能切换会话，写入前固定边界，返回后不能用新会话接收旧结果。
    const session=identity(), permissions=state.user.value?.permissions.slice().sort().join('|'), epoch=editTicket
    const row = await write(async () => {
      const result = await window.nexora!.callApi('deleteProductModel', {id:model.id, version:model.version, reason})
      validateProductResult('deleteProductModel', result)
      if (result.id !== model.id) throw Error('服务端返回了另一产品系列的删除结果')
      return result
    })
    if (!row || identity()!==session || epoch!==editTicket || state.user.value?.permissions.slice().sort().join('|')!==permissions || !allowed('catalog.manage')) return false
    // 服务端已确认没有子机型；仅清理失效的系列选择，其他产品草稿字段保留。
    state.productModels.value = state.productModels.value.filter(item => item.id !== row.id)
    if (state.productQuery.value.model_id === row.id) {closeProduct(); state.productQuery.value.model_id = null}
    if (state.productForm.value.model_id === row.id) state.productForm.value.model_id = null
    if (state.productModelForm.value.id === row.id) {
      state.productModelForm.value = {id:0,version:0,code:'',name:'',notes:'',reason:''}
      state.productModelChanges.value = []
    }
    state.notice.value = '空系列已删除，原编码与删除记录已保留。'
    await queryProducts(1)
    return identity() === session && allowed('catalog.manage')
  }
  async function applyProductLifecycle(product: ProductProfile, action: ProductLifecycleAction, reason: string): Promise<boolean> {
    // busy 解除时同步监听可能切换会话，写入前固定边界，返回后不能用新会话接收旧结果。
    const session=identity(), permissions=state.user.value?.permissions.slice().sort().join('|'), epoch=editTicket
    if (product.deleted_at) {state.error.value='子机型已删除，请刷新目录'; return false}
    const row = await write(async () => {
      // 停启复用既有生产用途开关，不再引入与 BOM 版本状态冲突的第二套 enabled 字段。
      const result = action === 'delete'
        ? await window.nexora!.callApi('deleteProduct',{id:product.id,version:product.version,reason})
        : await window.nexora!.callApi('updateProduct',{id:product.id,version:product.version,reason,
          kind:product.kind,model_id:product.model_id,configuration_name:product.configuration_name,
          can_sell:product.can_sell ?? true,can_purchase:product.can_purchase ?? true,can_produce:action==='enable'})
      validateProductResult(action === 'delete' ? 'deleteProduct' : 'updateProduct', result)
      if (result.id !== product.id || result.material_id !== product.material_id) throw Error('服务端返回了另一子机型的操作结果')
      if (action !== 'delete' && result.can_produce !== (action==='enable')) throw Error('子机型生产状态未生效，请升级服务端后重试')
      return result
    })
    if (!row || identity()!==session || epoch!==editTicket || state.user.value?.permissions.slice().sort().join('|')!==permissions || !allowed('catalog.manage')) return false
    const enabled = !row.deleted_at && row.can_produce !== false
    // 立即同步可生产性，旧工单草稿及 BOM 详情不能继续显示一个可用的建单入口。
    const updateBoms = (rows: Bom[]): Bom[] => rows.map(bom => bom.product_material_id === row.material_id
      ? {...bom,product_can_produce:enabled} : bom)
    state.boms.value = updateBoms(state.boms.value)
    state.productBomRecords.value = updateBoms(state.productBomRecords.value)
    if (state.bomDetailRecord.value?.product_material_id === row.material_id)
      state.bomDetailRecord.value = {...state.bomDetailRecord.value,product_can_produce:enabled}
    if (action === 'delete') {
      if (state.productDetailId.value === row.id) {
        closeProduct(); state.productDetailRecord.value=null; state.productBomRecords.value=[]; state.productChangeRecords.value=[]
      }
      if (state.productForm.value.id === row.id) {
        state.productEditorOpen.value=false
        state.productForm.value={id:0,version:0,mode:'new',material_id:0,kind:'finished',model_id:null,
          configuration_name:'',can_sell:true,can_purchase:true,can_produce:true,reason:''}
      }
      state.notice.value='子机型已删除，原物料、库存、BOM 和历史单据已保留。'
    } else {
      if (state.productDetailId.value === row.id) state.productDetailRecord.value=row
      state.notice.value=enabled ? '子机型已启用，可使用启用版本创建新生产工单。' : '子机型已停用，禁止新生产，已有工单和 BOM 版本保留。'
    }
    await queryProducts()
    if (identity() !== session || !allowed('catalog.manage')) return false
    if (action !== 'delete' && state.productDetailId.value === row.id) await openProduct(row.id)
    return identity() === session && allowed('catalog.manage')
  }
  // 复用原编辑票据取消未完成读取，不清空用户已输入的同系列草稿。
  function cancelProductModelEdit(): void { editTicket++ }
  async function editProductModel(id: number): Promise<ProductModel | undefined> {
    if (!allowed('catalog.manage') || state.busy.value || !Number.isSafeInteger(id) || id <= 0) return
    const ticket = ++editTicket
    const ownsRead = (): boolean => ticket === editTicket && allowed('catalog.manage')
    try {
      const [row, changes] = await Promise.all([window.nexora!.callApi('productModelDetail', {id}), window.nexora!.callApi('productModelChanges', {id})])
      if (!ownsRead()) return
      if (row.id !== id) throw Error('服务端返回了另一产品系列的资料')
      validateProductResult('productModelDetail', row); validateProductResult('productModelChanges', changes)
      if (row.deleted_at) throw Error('产品系列已删除，请刷新目录')
      state.productModelForm.value = {...row, reason: ''}
      // 同步订阅也可能切换会话；不能在新账号中继续补入旧系列审计记录。
      if (!ownsRead()) return
      state.productModelChanges.value = changes
      if (ownsRead()) return row
    } catch (cause) {if (ownsRead()) state.error.value = displayError(cause)}
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
  return {queryProducts, loadMoreProducts, openProduct, closeProduct, loadProductChanges, startProduct, saveProduct, saveProductModel, editProductModel, cancelProductModelEdit, deleteProductModel, applyProductLifecycle,
    prepareProductBom, openBomDetail, closeBomDetail}
}
