import type { Warehouse } from '../../../../shared/erp-api'
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

  async function postStockAdjustment(adjustmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postStockAdjustment', { adjustmentId }),
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
        paged: true,
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
        reason: 'other', note: '', reference: '', lines: [{ material_id: 0, quantity: '1' }] }
    }, '其他入库草稿已创建。')
  }

  async function postOtherInbound(inboundId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postOtherInbound', { inboundId }),
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

  async function postWarehouseOutbound(outboundId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('postWarehouseOutbound', { outboundId }),
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

  async function postTransfer(transferId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postTransfer', { transferId }),
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

  async function postStocktake(stocktakeId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postStocktake', { stocktakeId }),
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

  async function saveWarehouse(data: Omit<Warehouse, 'id'>, id?: number): Promise<boolean> {
    if (!window.nexora) return false
    let saved = false
    await perform(async () => {
      if (id) await window.nexora!.callApi('updateWarehouse', { ...data, id })
      else await window.nexora!.callApi('createWarehouse', { ...data })
      saved = true
    }, '仓库已保存。')
    return saved
  }

  async function deleteWarehouse(id: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('deleteWarehouse', { id }), '仓库已删除。')
  }

  return {
    createStockAdjustment,
    submitStockAdjustment,
    approveStockAdjustment,
    rejectStockAdjustment,
    cancelStockAdjustment,
    postStockAdjustment,
    reverseStockAdjustment,
    queryLedger,
    createOtherInbound,
    postOtherInbound,
    cancelOtherInbound,
    reverseOtherInbound,
    createOtherOutbound,
    postWarehouseOutbound,
    cancelOtherOutbound,
    reverseOtherOutbound,
    saveWarehouse,
    deleteWarehouse,
    createWarehouse,
    createTransfer,
    postTransfer,
    reverseTransfer,
    createStocktake,
    postStocktake,
    cancelStocktake,
    reverseStocktake
  }
}
