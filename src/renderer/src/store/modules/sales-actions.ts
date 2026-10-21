import type { ErpOperations, Stock } from '../../../../shared/erp-api'
import type { SalesDraftType, SalesDraftChange } from '../../../../shared/sales-draft-api'
import { captureSession } from '../session-state.ts'
import { materialUseIssue } from '../../utils/material-use.ts'
import type { AppState } from '../state'
import type {ShipmentLotLineInput,ShipmentLotOptions} from '../../../../shared/shipment-lot-api'
import type {SalesReturnLotLineInput,SalesReturnLotOptions} from '../../../../shared/sales-return-lot-api'
import type {CustomerImportResult,SalesOrderContract,SalesOrderContractAttachment,
  SalesOrderContractAttachmentList} from '../../../../shared/erp-api'
import {watch} from 'vue'
import {displayError} from '../../utils/formatters.ts'

// 销售单据操作独立维护；写入后由统一入口刷新服务端快照。
export function createSalesActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const {
    salesOrders,
    shipments,
    salesReturnReversalReasons,
    shipmentReversalReasons,
    customerForm,
    salesForm,
    shipmentForm,
    salesReturnForm
  } = state

  async function createCustomer(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createCustomer', {
        name: customerForm.value.name
      })
      customerForm.value = { name: '' }
    }, '客户已创建。')
  }

  async function importCustomerNames(names: string[], reason: string,
                                     allowSimilar: boolean): Promise<CustomerImportResult | null> {
    if (!window.nexora) return null
    const completion: { result?: CustomerImportResult } = {}
    const actorId = state.user.value?.id
    await perform(async () => {
      completion.result = await window.nexora!.callApi('importCustomers', {
        names, reason, allow_similar: allowSimilar
      })
    }, '客户已批量导入。')
    if (actorId !== state.user.value?.id) {
      state.notice.value = ''
      return completion.result ?? null
    }
    if (completion.result) {
      // 写入已成功但快照刷新失败时仍返回结果，避免重复提交同一批次。
      state.notice.value = state.error.value
        ? `已导入 ${completion.result.created.length} 位客户，批次摘要 ${completion.result.batch_reference}；名单刷新失败，请使用工作台刷新。`
        : `已导入 ${completion.result.created.length} 位客户，批次摘要 ${completion.result.batch_reference}。`
      state.error.value = ''
    }
    return completion.result ?? null
  }

  async function createSalesOrder(input?: ErpOperations['createSalesOrder']['input']): Promise<void> {
    if (!window.nexora) return
    const form = input ?? salesForm.value
    await perform(async () => {
      const issue = materialUseIssue(form.lines, state.materials.value, 'can_sell')
      if (issue) throw new Error(issue)
      // 销售单价和数量只从表单读取，服务端独立计算订单金额与出库进度。
      await window.nexora!.callApi('createSalesOrder', {
        customer_id: form.customer_id,
        reference: form.reference,
        lines: form.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity,
          unit_price: line.unit_price,
          warranty_days: line.warranty_days,
          warranty_basis: line.warranty_basis
        }))
      })
      if (!input) salesForm.value = {
        customer_id: 0,
        reference: '',
        lines: [{ material_id: 0, quantity: '1', unit_price: '0', warranty_days: null, warranty_basis: '' }]
      }
    }, '销售订单草稿已创建。')
  }

  let contractEpoch = 0
  // 合同与附件属于同一实例、证书及权限会话；普通账号快照刷新不应误伤在途读取。
  // 角色与权限按集合比较，副本排序不会修改用户快照，例行返回顺序变化也不取消读取。
  watch(() => `${state.server?.value?.id}:${state.server?.value?.fingerprint}:${state.user?.value?.id}:${state.user?.value?.roles?.slice().sort().join('|')}:${state.user?.value?.permissions?.slice().sort().join('|')}:${state.connectionLost?.value}`,
    () => { contractEpoch++ }, { flush: 'sync' })

  async function loadSalesOrderContract(orderId: number): Promise<SalesOrderContract | null> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view')) return null
    const owner = contractEpoch
    try {
      const result = await window.nexora.callApi('salesOrderContract', { orderId })
      return owner === contractEpoch && !state.connectionLost.value &&
        !!state.user.value?.permissions.includes('sales.view') ? result : null
    } catch (cause) {
      if (owner === contractEpoch) state.error.value = displayError(cause)
      return null
    }
  }

  async function reviseSalesOrderContract(orderId: number, expected_version: number,
    body: string, acceptance_reference: string, reason: string): Promise<SalesOrderContract | null> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales_order.confirm')) return null
    const owner = contractEpoch
    let saved: SalesOrderContract | null = null
    await perform(async () => {
      // 排队提交期间切换会话后，不能向新的服务端发送原合同的写入。
      if (owner !== contractEpoch || state.connectionLost.value || !state.user.value?.permissions.includes('sales_order.confirm')) {
        throw new Error('会话或连接已变化，请重新打开销售合同。')
      }
      saved = await window.nexora!.callApi('reviseSalesOrderContract', {
        orderId, expected_version, body, acceptance_reference, reason
      })
    }, `销售订单 #${orderId} 合同正文已追加修订，原版本保留。`)
    return owner === contractEpoch && !state.connectionLost.value && !!state.user.value?.permissions.includes('sales_order.confirm') ? saved : null
  }

  const contractAttachmentOwner = (): number => contractEpoch

  async function loadSalesContractAttachments(orderId: number, revisionId: number): Promise<SalesOrderContractAttachmentList> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view')) {
      throw new Error('会话或权限已变化，请重新读取合同附件')
    }
    const owner = contractAttachmentOwner()
    const result = await window.nexora.callApi('salesContractAttachments', { orderId, revisionId })
    if (owner !== contractAttachmentOwner() || !state.user.value?.permissions.includes('sales.view')) {
      throw new Error('会话或权限已变化，请重新读取合同附件')
    }
    return result
  }

  async function uploadSalesContractAttachment(orderId: number, revisionId: number,
    reason: string): Promise<SalesOrderContractAttachment | null> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view')
      || !state.user.value.permissions.includes('sales_order.confirm')) {
      throw new Error('会话或权限已变化，请重新上传合同附件')
    }
    const owner = contractAttachmentOwner()
    const result = await window.nexora.uploadSalesContractAttachment(orderId, revisionId, reason)
    if (owner !== contractAttachmentOwner() || !state.user.value?.permissions.includes('sales_order.confirm')) {
      throw new Error('会话或权限已变化，请刷新合同附件')
    }
    return result
  }

  async function reverseSalesContractAttachment(orderId: number, revisionId: number,
    attachmentId: number, reason: string): Promise<SalesOrderContractAttachment> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view')
      || !state.user.value.permissions.includes('sales_order.confirm')) {
      throw new Error('会话或权限已变化，请重新撤销合同附件')
    }
    const owner = contractAttachmentOwner()
    const result = await window.nexora.callApi('reverseSalesContractAttachment', {
      orderId, revisionId, attachmentId, reason
    })
    if (owner !== contractAttachmentOwner() || !state.user.value?.permissions.includes('sales_order.confirm')) {
      throw new Error('会话或权限已变化，请刷新合同附件')
    }
    return result
  }

  async function saveSalesContractAttachment(orderId: number, revisionId: number,
    attachmentId: number): Promise<string | null> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view')) {
      throw new Error('会话或权限已变化，请重新读取合同附件')
    }
    const owner = contractAttachmentOwner()
    const result = await window.nexora.saveSalesContractAttachment(orderId, revisionId, attachmentId)
    if (owner !== contractAttachmentOwner() || !state.user.value?.permissions.includes('sales.view')) {
      throw new Error('会话或权限已变化，请重新读取合同附件')
    }
    return result
  }

  async function confirmSalesOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('confirmSalesOrder', { orderId }),
      `销售订单 #${orderId} 已确认，可创建出库单。`
    )
  }

  async function cancelSalesOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelSalesOrder', { orderId }),
      `销售订单 #${orderId} 已取消。`
    )
  }

  async function closeSalesOrder(input: ErpOperations['closeSalesOrder']['input']): Promise<boolean> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales_order.cancel')) return false
    const owns = captureSession(state)
    let saved = false
    await perform(async () => {
      if (!owns() || state.connectionLost.value) throw Error('会话已变化，请重新核对订单。')
      await window.nexora!.callApi('closeSalesOrder', input)
      saved = true
    }, '剩余交付已终止，原订单、出库和财务记录保留。')
    // 终止已成功时，即使刷新失败也关闭确认框，避免用户重复操作。
    return saved && owns()
  }

  function chooseShipmentOrder(): void {
    const order = salesOrders.value.find(
      (item) => item.id === shipmentForm.value.sales_order_id
    )
    // 订单选择后仅填入未出库明细，最终数量仍由操作人填写并由服务端复核。
    shipmentForm.value.lines = order?.lines
      .filter((line) => Number(line.remaining_quantity) > 0)
      .map((line) => ({
        material_id: line.material_id,
        quantity: line.remaining_quantity
      })) ?? [{ material_id: 0, quantity: '1' }]
  }

  async function createShipment(input?: ErpOperations['createShipment']['input']): Promise<void> {
    if (!window.nexora) return
    const form = input ?? shipmentForm.value
    await perform(async () => {
      await window.nexora!.callApi('createShipment', {
        sales_order_id: form.sales_order_id,
        warehouse_id: form.warehouse_id,
        reference: form.reference,
        lines: form.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity
        }))
      })
      if (!input) shipmentForm.value = {
        sales_order_id: 0,
        warehouse_id: form.warehouse_id,
        reference: '',
        lines: [{ material_id: 0, quantity: '1' }]
      }
    }, '出库单草稿已创建。')
  }

  async function loadAvailableShipmentLots(shipmentId: number): Promise<ShipmentLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('shipment.post'))
      throw Error('当前账号无法读取销售出库批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableShipmentLots', {shipmentId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('shipment.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postShipment(shipmentId: number, lines?: ShipmentLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postShipment', { shipmentId, lines }),
      `出库单 #${shipmentId} 已确认，仓库库存与订单进度已更新。`
    )
  }

  async function cancelShipment(shipmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelShipment', { shipmentId }),
      `出库单 #${shipmentId} 已取消。`
    )
  }

  async function reverseShipment(shipmentId: number): Promise<void> {
    if (!window.nexora) return
    const reason = shipmentReversalReasons.value[shipmentId]?.trim() ?? ''
    // 页面只提交原因；退货依赖、库存补回和应收更正由服务端处理。
    await perform(async () => {
      await window.nexora!.callApi('reverseShipment', { shipmentId, reason })
      delete shipmentReversalReasons.value[shipmentId]
    }, `出库单 #${shipmentId} 已冲销，原仓库存与应收已追加更正记录。`)
  }

  function chooseSalesReturnShipment(): void {
    const shipment = shipments.value.find(
      (item) => item.id === salesReturnForm.value.shipment_id
    )
    // 只预填原出库中仍可退的明细；创建和确认时服务端会分别复核累计数量。
    salesReturnForm.value.lines =
      shipment?.lines
        .filter((line) => Number(line.returnable_quantity) > 0)
        .map((line) => ({
          shipment_line_id: line.id,
          quantity: line.returnable_quantity
        })) ?? []
    if (shipment) salesReturnForm.value.warehouse_id = shipment.warehouse_id
  }

  async function createSalesReturn(input?: ErpOperations['createSalesReturn']['input']): Promise<void> {
    const form = input ?? salesReturnForm.value
    if (!window.nexora || !form.lines.length) return
    await perform(async () => {
      await window.nexora!.callApi('createSalesReturn', {
        shipment_id: form.shipment_id,
        warehouse_id: form.warehouse_id,
        reason: form.reason,
        lines: form.lines.map((line) => ({ ...line }))
      })
      if (!input) salesReturnForm.value = {
        shipment_id: 0,
        warehouse_id: form.warehouse_id,
        reason: '',
        lines: []
      }
    }, '销售退货草稿已创建。')
  }

  async function loadAvailableSalesReturnLots(returnId: number): Promise<SalesReturnLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('sales_return.post'))
      throw Error('当前账号无法读取原出库批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableSalesReturnLots', {returnId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('sales_return.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postSalesReturn(returnId: number, lines?: SalesReturnLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postSalesReturn', { returnId, lines }),
      `销售退货单 #${returnId} 已确认，退回库存已入仓。`
    )
  }

  async function cancelSalesReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelSalesReturn', { returnId }),
      `销售退货单 #${returnId} 已取消。`
    )
  }

  async function reverseSalesReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    const reason = salesReturnReversalReasons.value[returnId]?.trim() ?? ''
    // 页面只收集原因；库存不足和重复冲销由服务端在写事务内拦截。
    await perform(async () => {
      await window.nexora!.callApi('reverseSalesReturn', { returnId, reason })
      delete salesReturnReversalReasons.value[returnId]
    }, `销售退货单 #${returnId} 已冲销，库存与应收已追加更正记录。`)
  }

  async function reviseSalesDraft<K extends 'reviseSalesOrder' | 'reviseShipment' | 'reviseSalesReturn'>(
    action: K, input: ErpOperations[K]['input']
  ): Promise<boolean> {
    const permission = {reviseSalesOrder:'sales_order.create', reviseShipment:'shipment.create',
      reviseSalesReturn:'sales_return.create'}[action]
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes(permission)) return false
    const owns = captureSession(state)
    let saved = false
    await perform(async () => {
      if (!owns() || state.connectionLost.value) throw Error('会话已变化，请重新打开草稿。')
      await window.nexora!.callApi(action, input)
      saved = true
    }, '草稿修订已保存，原版本已保留；请核对后重新提交审批。')
    // 写入成功与列表刷新分开判断，刷新失败也不能让用户重复保存同一修订。
    return saved && owns()
  }

  async function loadSalesDraftChanges(documentType: SalesDraftType, documentId: number): Promise<SalesDraftChange[]> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('sales.view'))
      throw Error('当前会话无法查看修订历史。')
    const owns = captureSession(state)
    const rows = await window.nexora.callApi('salesDraftChanges', {documentType, documentId})
    if (!owns() || state.connectionLost.value) throw Error('会话已变化，请重新查看修订历史。')
    return rows
  }

  async function loadShipmentStock(warehouseId: number): Promise<Stock[]> {
    if (!window.nexora || state.connectionLost.value || !state.user.value?.permissions.includes('inventory.view'))
      throw Error('当前账号没有库存查看权限。')
    const owns = captureSession(state)
    const rows = await window.nexora.callApi('stock', {warehouseId})
    if (!owns() || state.connectionLost.value) throw Error('会话已变化，请重新读取仓库库存。')
    return rows
  }

  return {
    reviseSalesDraft,
    loadSalesDraftChanges,
    loadShipmentStock,
    createCustomer,
    importCustomerNames,
    createSalesOrder,
    loadSalesOrderContract,
    reviseSalesOrderContract,
    loadSalesContractAttachments,
    uploadSalesContractAttachment,
    reverseSalesContractAttachment,
    saveSalesContractAttachment,
    confirmSalesOrder,
    cancelSalesOrder,
    closeSalesOrder,
    chooseShipmentOrder,
    createShipment,
    loadAvailableShipmentLots,
    postShipment,
    cancelShipment,
    reverseShipment,
    chooseSalesReturnShipment,
    createSalesReturn,
    loadAvailableSalesReturnLots,
    postSalesReturn,
    cancelSalesReturn,
    reverseSalesReturn
  }
}
