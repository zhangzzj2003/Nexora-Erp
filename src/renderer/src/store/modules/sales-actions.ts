import type { AppState } from '../state'

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
    customerEdit,
    customerHistory,
    salesForm,
    shipmentForm,
    salesReturnForm
  } = state

  async function createCustomer(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createCustomer', {
        ...customerForm.value
      })
      customerForm.value = { name: '' }
    }, '客户已创建。')
  }

  async function updateCustomer(): Promise<void> {
    if (!window.nexora || !customerEdit.value) return
    await perform(async () => {
      await window.nexora!.callApi('updateCustomer', { ...customerEdit.value! })
      customerEdit.value = null
    }, '客户资料已更新；历史订单归属保持原记录。')
  }

  async function loadCustomerHistory(id: number): Promise<void> {
    if (!window.nexora) return
    customerHistory.value = []
    await perform(async () => {
      customerHistory.value = await window.nexora!.callApi('customerHistory', { id })
    }, '客户修改记录已读取。')
  }

  async function transferSalesOwner(orderId: number, owner_id: number, version: number, reason: string): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('transferSalesOwner', { orderId, owner_id, version, reason }), '订单负责商务已转交。')
  }

  async function createSalesOrder(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      // 销售单价和数量只从表单读取，服务端独立计算订单金额与出库进度。
      await window.nexora!.callApi('createSalesOrder', {
        customer_id: salesForm.value.customer_id,
        reference: salesForm.value.reference,
        lines: salesForm.value.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity,
          unit_price: line.unit_price, tax_rate: line.tax_rate, discount_rate: line.discount_rate, includes_tax: line.includes_tax
        }))
      })
      salesForm.value = {
        customer_id: 0,
        reference: '',
        lines: [{ material_id: 0, quantity: '1', unit_price: '0', tax_rate: '0', discount_rate: '0', includes_tax: false }]
      }
    }, '销售订单草稿已创建。')
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

  async function createShipment(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createShipment', {
        sales_order_id: shipmentForm.value.sales_order_id,
        warehouse_id: shipmentForm.value.warehouse_id,
        reference: shipmentForm.value.reference,
        lines: shipmentForm.value.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity
        }))
      })
      shipmentForm.value = {
        sales_order_id: 0,
        warehouse_id: shipmentForm.value.warehouse_id,
        reference: '',
        lines: [{ material_id: 0, quantity: '1' }]
      }
    }, '出库单草稿已创建。')
  }

  async function postShipment(shipmentId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postShipment', { shipmentId }),
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

  async function createSalesReturn(): Promise<void> {
    if (!window.nexora || !salesReturnForm.value.lines.length) return
    await perform(async () => {
      await window.nexora!.callApi('createSalesReturn', {
        shipment_id: salesReturnForm.value.shipment_id,
        warehouse_id: salesReturnForm.value.warehouse_id,
        reason: salesReturnForm.value.reason,
        lines: salesReturnForm.value.lines.map((line) => ({ ...line }))
      })
      salesReturnForm.value = {
        shipment_id: 0,
        warehouse_id: salesReturnForm.value.warehouse_id,
        reason: '',
        lines: []
      }
    }, '销售退货草稿已创建。')
  }

  async function postSalesReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postSalesReturn', { returnId }),
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

  return {
    createCustomer,
    updateCustomer,
    loadCustomerHistory,
    transferSalesOwner,
    createSalesOrder,
    confirmSalesOrder,
    cancelSalesOrder,
    chooseShipmentOrder,
    createShipment,
    postShipment,
    cancelShipment,
    reverseShipment,
    chooseSalesReturnShipment,
    createSalesReturn,
    postSalesReturn,
    cancelSalesReturn,
    reverseSalesReturn
  }
}
