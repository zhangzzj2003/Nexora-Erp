import type { ErpOperations, Warehouse } from '../../../../shared/erp-api'
import type {OutboundLotLineInput, OutboundLotOptions} from '../../../../shared/outbound-lot-api'
import type {TransferLotLineInput, TransferLotOptions} from '../../../../shared/transfer-lot-api'
import type {StocktakeLotLineInput, StocktakeLotOptions} from '../../../../shared/stocktake-lot-api'
import type {AdjustmentLotLineInput, AdjustmentLotOptions} from '../../../../shared/adjustment-lot-api'
import { documentMaterialIssue } from '../../utils/document-material-lines.ts'
import type { AppState } from '../state'

// 仓库与盘点操作独立维护；写入后由统一入口刷新服务端快照。
export function createWarehouseActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const {
    warehouseForm,
    otherInboundForm,
    otherInboundReversalReasons,
    otherOutboundForm,
    otherOutboundReversalReasons,
    ledgerResult,
    ledgerQuery,
    adjustmentForm,
    adjustmentDecisionReasons,
    adjustmentReversalReasons,
    transferForm,
    transferReversalReasons,
    stocktakeForm,
    stocktakeReversalReasons
  } = state

  // 调整审批与仓库确认分步执行，每一步都由服务端检查状态与操作者。
  async function createStockAdjustment(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createStockAdjustment', {
        ...adjustmentForm.value,
        lines: adjustmentForm.value.lines.map((line) => ({ ...line }))
      })
      adjustmentForm.value = { warehouse_id: adjustmentForm.value.warehouse_id,
        reason: '', reference: '', lines: [{ material_id: 0, quantity: '1' }] }
    }, '库存调整草稿已创建。')
  }

  async function submitStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('submitStockAdjustment', { adjustmentId }),
      `调整单 #${adjustmentId} 已提交审批。`)
  }

  async function approveStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('approveStockAdjustment', { adjustmentId }),
      `调整单 #${adjustmentId} 已审批。`)
  }

  async function rejectStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    const reason = adjustmentDecisionReasons.value[adjustmentId]?.trim() ?? ''
    await perform(() => window.nexora!.callApi('rejectStockAdjustment', { adjustmentId, reason }),
      `调整单 #${adjustmentId} 已驳回。`)
  }

  async function cancelStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('cancelStockAdjustment', { adjustmentId }),
      `调整单 #${adjustmentId} 已取消。`)
  }

  async function loadAvailableAdjustmentLots(adjustmentId: number): Promise<AdjustmentLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('adjustment.post'))
      throw Error('当前账号无法读取调整批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableAdjustmentLots', {adjustmentId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('adjustment.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postStockAdjustment(adjustmentId: number,
                                     lines?: AdjustmentLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postStockAdjustment', { adjustmentId, lines }),
      `调整单 #${adjustmentId} 已由仓库确认。`)
  }

  async function reverseStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    const reason = adjustmentReversalReasons.value[adjustmentId]?.trim() ?? ''
    await perform(() => window.nexora!.callApi('reverseStockAdjustment', { adjustmentId, reason }),
      `调整单 #${adjustmentId} 已冲销。`)
  }

  async function queryLedger(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      // 复制当前筛选条件，避免跨进程发送 Vue 响应式代理对象。
      ledgerResult.value = await window.nexora!.callApi('inventoryLedger', {
        ...ledgerQuery.value,
        from_date: ledgerQuery.value.from_date || null,
        to_date: ledgerQuery.value.to_date || null
      })
    }, '库存台账已更新。')
  }

  async function createOtherInbound(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createOtherInbound', {
        ...otherInboundForm.value,
        lines: otherInboundForm.value.lines.map((line) => ({ ...line }))
      })
      otherInboundForm.value = { warehouse_id: otherInboundForm.value.warehouse_id,
        reason: 'other', note: '', reference: '', lines: [] }
    }, '其他入库草稿已创建。')
  }

  // 仅复制可编辑业务字段；原单身份、审批、确认记录和实物批次永远不进入新建请求。
  function prepareOtherInboundReopen(inboundId: number): boolean {
    const inbound = state.otherInbounds.value.find(item => item.id === inboundId)
    if (!canReopenOtherInbound() || inbound?.status !== 'cancelled') return false
    state.otherInboundReopenForms.value[inboundId] ??= {
      warehouse_id: inbound.warehouse_id, reason: inbound.reason,
      note: inbound.note, reference: inbound.reference,
      lines: inbound.lines.map(line => ({ material_id: line.material_id, quantity: line.quantity }))
    }
    return true
  }

  function canReopenOtherInbound(): boolean {
    return !state.busy.value && !state.connectionLost.value
      && !!state.user.value?.permissions.includes('other_inbound.create')
  }

  async function createReopenedOtherInbound(inboundId: number): Promise<void> {
    if (!window.nexora || !canReopenOtherInbound()) return
    const source = state.otherInbounds.value.find(item => item.id === inboundId)
    const draft = state.otherInboundReopenForms.value[inboundId]
    if (source?.status !== 'cancelled' || !draft) {
      state.error.value = '原单状态已变化，请重新打开重开单。'
      return
    }
    const issue = documentMaterialIssue(draft.lines, state.materials.value)
      || (!state.warehouses.value.some(item => item.id === draft.warehouse_id) ? '请选择可用仓库。' : '')
    if (issue) { state.error.value = issue; return }
    await perform(async () => {
      // 走标准新建接口，由服务端生成新单号和新明细，并重新开始审批流程。
      await window.nexora!.callApi('createOtherInbound', {
        warehouse_id: draft.warehouse_id, reason: draft.reason, note: draft.note, reference: draft.reference,
        lines: draft.lines.map(line => ({ material_id: line.material_id, quantity: line.quantity }))
      })
      // 失败不清空输入；成功只移除当前原单对应的重开草稿。
      if (state.otherInboundReopenForms.value[inboundId] === draft) delete state.otherInboundReopenForms.value[inboundId]
    }, '重开单已保存为新的其他入库草稿，请重新送审。')
  }

  async function postOtherInbound(inboundId: number,
                                  lines?: ErpOperations['postOtherInbound']['input']['lines']): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postOtherInbound', { inboundId, lines }),
      `其他入库单 #${inboundId} 已确认，库存流水已生成。`)
  }

  async function cancelOtherInbound(inboundId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('cancelOtherInbound', { inboundId }),
      `其他入库单 #${inboundId} 已取消。`)
  }

  async function reverseOtherInbound(inboundId: number): Promise<void> {
    if (!window.nexora) return
    const reason = otherInboundReversalReasons.value[inboundId]?.trim() ?? ''
    await perform(async () => {
      await window.nexora!.callApi('reverseOtherInbound', { inboundId, reason })
      delete otherInboundReversalReasons.value[inboundId]
    }, `其他入库单 #${inboundId} 已冲销。`)
  }

  // 其他出库草稿不影响库存；仓库确认后再刷新余额与台账。
  async function createOtherOutbound(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createOtherOutbound', {
        ...otherOutboundForm.value,
        lines: otherOutboundForm.value.lines.map((line) => ({ ...line }))
      })
      otherOutboundForm.value = { warehouse_id: otherOutboundForm.value.warehouse_id,
        reason: 'other', note: '', reference: '', lines: [{ material_id: 0, quantity: '1' }] }
    }, '其他出库草稿已创建。')
  }

  async function loadAvailableOutboundLots(outboundId: number): Promise<OutboundLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('other_outbound.post'))
      throw Error('当前账号无法读取仓库出库批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableOutboundLots', {outboundId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('other_outbound.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postWarehouseOutbound(outboundId: number, lines?: OutboundLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postWarehouseOutbound', { outboundId, lines }),
      `仓库出库单 #${outboundId} 已确认，库存流水已生成。`)
  }

  async function cancelOtherOutbound(outboundId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('cancelOtherOutbound', { outboundId }),
      `其他出库单 #${outboundId} 已取消。`)
  }

  async function reverseOtherOutbound(outboundId: number): Promise<void> {
    if (!window.nexora) return
    const reason = otherOutboundReversalReasons.value[outboundId]?.trim() ?? ''
    await perform(async () => {
      await window.nexora!.callApi('reverseOtherOutbound', { outboundId, reason })
      delete otherOutboundReversalReasons.value[outboundId]
    }, `其他出库单 #${outboundId} 已冲销。`)
  }

  async function createWarehouse(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createWarehouse', {
        ...warehouseForm.value
      })
      warehouseForm.value = { code: '', name: '' }
    }, '仓库已创建。')
  }

  async function createTransfer(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      // 只发送表单字段，避免把 Vue 响应式对象传入进程通信。
      await window.nexora!.callApi('createTransfer', {
        from_warehouse_id: transferForm.value.from_warehouse_id,
        to_warehouse_id: transferForm.value.to_warehouse_id,
        reference: transferForm.value.reference,
        lines: transferForm.value.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity
        }))
      })
      transferForm.value = {
        from_warehouse_id: transferForm.value.from_warehouse_id,
        to_warehouse_id: 0,
        reference: '',
        lines: [{ material_id: 0, quantity: '1' }]
      }
    }, '调拨单草稿已创建。')
  }

  async function loadAvailableTransferLots(transferId: number): Promise<TransferLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('transfer.post'))
      throw Error('当前账号无法读取调拨批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableTransferLots', {transferId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('transfer.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postTransfer(transferId: number, lines?: TransferLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postTransfer', { transferId, lines }),
      `调拨单 #${transferId} 已确认，双向库存流水已生成。`
    )
  }

  async function reverseTransfer(transferId: number): Promise<void> {
    if (!window.nexora) return
    const reason = transferReversalReasons.value[transferId] ?? ''
    await perform(async () => {
      await window.nexora!.callApi('reverseTransfer', { transferId, reason })
      delete transferReversalReasons.value[transferId]
    }, `调拨单 #${transferId} 已冲销，库存已按原路径退回。`)
  }

  async function createStocktake(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      // 仅传实盘量；账面快照由服务端在事务内生成，防止客户端伪造差异。
      await window.nexora!.callApi('createStocktake', {
        warehouse_id: stocktakeForm.value.warehouse_id,
        reference: stocktakeForm.value.reference,
        lines: stocktakeForm.value.lines.map((line) => ({
          material_id: line.material_id,
          counted_quantity: line.counted_quantity
        }))
      })
      stocktakeForm.value = {
        warehouse_id: stocktakeForm.value.warehouse_id,
        reference: '',
        lines: [{ material_id: 0, counted_quantity: '0' }]
      }
    }, '盘点草稿已创建，请核对账面与实盘数量。')
  }

  async function loadAvailableStocktakeLots(stocktakeId: number): Promise<StocktakeLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('stocktake.post'))
      throw Error('当前账号无法读取盘点批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableStocktakeLots', {stocktakeId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('stocktake.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postStocktake(stocktakeId: number, lines?: StocktakeLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postStocktake', { stocktakeId, lines }),
      `盘点单 #${stocktakeId} 已确认，差异已记入库存流水。`
    )
  }

  async function cancelStocktake(stocktakeId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelStocktake', { stocktakeId }),
      `盘点单 #${stocktakeId} 已取消。`
    )
  }

  async function reverseStocktake(stocktakeId: number): Promise<void> {
    if (!window.nexora) return
    const reason = stocktakeReversalReasons.value[stocktakeId] ?? ''
    await perform(async () => {
      await window.nexora!.callApi('reverseStocktake', { stocktakeId, reason })
      delete stocktakeReversalReasons.value[stocktakeId]
    }, `盘点单 #${stocktakeId} 已冲销，反向差异已记入库存流水。`)
  }

  async function saveWarehouse(data: Pick<Warehouse, 'code' | 'name'> & { version?: number; reason?: string }, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      if (id) {
        if (!data.version || !data.reason?.trim()) throw new Error('请重新读取仓库版本并填写修改原因。')
        await window.nexora!.callApi('updateWarehouse', { code: data.code, name: data.name,
          version: data.version, reason: data.reason, id })
      } else await window.nexora!.callApi('createWarehouse', { code: data.code, name: data.name })
      saved = true
    }, '仓库已保存。')
    return saved
  }

  async function deleteWarehouse(id: number, version: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('deleteWarehouse', { id, version }), '仓库已删除。')
  }

  return {
    createStockAdjustment,
    submitStockAdjustment,
    approveStockAdjustment,
    rejectStockAdjustment,
    cancelStockAdjustment,
    loadAvailableAdjustmentLots,
    postStockAdjustment,
    reverseStockAdjustment,
    queryLedger,
    createOtherInbound,
    prepareOtherInboundReopen,
    createReopenedOtherInbound,
    postOtherInbound,
    cancelOtherInbound,
    reverseOtherInbound,
    createOtherOutbound,
    loadAvailableOutboundLots,
    postWarehouseOutbound,
    cancelOtherOutbound,
    reverseOtherOutbound,
    saveWarehouse,
    deleteWarehouse,
    createWarehouse,
    createTransfer,
    loadAvailableTransferLots,
    postTransfer,
    reverseTransfer,
    createStocktake,
    loadAvailableStocktakeLots,
    postStocktake,
    cancelStocktake,
    reverseStocktake
  }
}
