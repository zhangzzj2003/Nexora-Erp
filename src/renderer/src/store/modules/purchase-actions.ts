import type { AppState } from '../state'

// 采购单据操作独立维护；写入后由统一入口刷新服务端快照。
export function createPurchaseActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>
) {
  const {
    purchaseOrders,
    goodsReceipts,
    goodsReceiptForm,
    purchaseRequests,
    purchaseRequestForm,
    requestConversionForm,
    requestRejectReasons,
    receiptForm,
    purchaseForm,
    purchaseReturnForm,
    purchaseReturnReversalReasons,
    receiptReversalReasons,
    selectedPurchaseReturnReceipt
  } = state

  function chooseGoodsReceiptOrder(): void {
    const order = purchaseOrders.value.find((item) => item.id === goodsReceiptForm.value.purchase_order_id)
    goodsReceiptForm.value.lines = order?.lines.flatMap((line) => {
      const pending = goodsReceipts.value.filter((item) => item.status === 'confirmed' && item.inbound_status === 'draft')
        .flatMap((item) => item.lines).filter((item) => item.purchase_order_line_id === line.id)
        .reduce((total, item) => total + Number(item.accepted_quantity), 0)
      const remaining = Math.max(0, Number(line.remaining_quantity) - pending)
      return remaining > 0 ? [{ purchase_order_line_id: line.id,
        accepted_quantity: remaining.toFixed(3), rejected_quantity: '0', rejection_reason: '' }] : []
    }) ?? []
  }

  async function createGoodsReceipt(): Promise<void> {
    if (!window.nexora || !goodsReceiptForm.value.lines.length) return
    await perform(async () => {
      await window.nexora!.callApi('createGoodsReceipt', {
        ...goodsReceiptForm.value,
        lines: goodsReceiptForm.value.lines.map((line) => ({ ...line }))
      })
      goodsReceiptForm.value = { purchase_order_id: 0, warehouse_id: goodsReceiptForm.value.warehouse_id,
        reference: '', lines: [] }
    }, '采购收货草稿已创建。')
  }

  async function confirmGoodsReceipt(goodsReceiptId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('confirmGoodsReceipt', { goodsReceiptId }),
      `采购收货 #${goodsReceiptId} 已确认，合格数量已生成待入库单。`)
  }

  async function cancelGoodsReceipt(goodsReceiptId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('cancelGoodsReceipt', { goodsReceiptId }),
      `采购收货 #${goodsReceiptId} 已取消。`)
  }

  function editPurchaseRequest(requestId?: number): void {
    const request = purchaseRequests.value.find((item) => item.id === requestId)
    purchaseRequestForm.value = request ? {
      requestId: request.id,
      reference: request.reference,
      note: request.note,
      lines: request.lines.map((line) => ({ material_id: line.material_id, quantity: line.quantity }))
    } : { requestId: null, reference: '', note: '', lines: [{ material_id: 0, quantity: '1' }] }
  }

  async function savePurchaseRequest(): Promise<void> {
    if (!window.nexora) return
    const { requestId, reference, note, lines } = purchaseRequestForm.value
    await perform(async () => {
      const payload = { reference, note, lines: lines.map((line) => ({ ...line })) }
      if (requestId) await window.nexora!.callApi('updatePurchaseRequest', { requestId, ...payload })
      else await window.nexora!.callApi('createPurchaseRequest', payload)
      editPurchaseRequest()
    }, requestId ? '采购申请已更新。' : '采购申请草稿已创建。')
  }

  async function submitPurchaseRequest(requestId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('submitPurchaseRequest', { requestId }), `采购申请 #${requestId} 已提交。`)
  }

  async function approvePurchaseRequest(requestId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('approvePurchaseRequest', { requestId }), `采购申请 #${requestId} 已批准。`)
  }

  async function rejectPurchaseRequest(requestId: number): Promise<void> {
    if (!window.nexora) return
    const reason = requestRejectReasons.value[requestId]?.trim() ?? ''
    await perform(async () => {
      await window.nexora!.callApi('rejectPurchaseRequest', { requestId, reason })
      delete requestRejectReasons.value[requestId]
    }, `采购申请 #${requestId} 已驳回。`)
  }

  async function cancelPurchaseRequest(requestId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('cancelPurchaseRequest', { requestId }), `采购申请 #${requestId} 已取消。`)
  }

  function selectRequestConversion(requestId: number): void {
    const request = purchaseRequests.value.find((item) => item.id === requestId)
    requestConversionForm.value = {
      requestId: request?.id ?? 0,
      supplier_id: 0,
      reference: '',
      // 每次选择申请都从服务端剩余量预填；允许把本批不采购的明细数量改为零。
      lines: request?.lines.filter((line) => Number(line.remaining_quantity) > 0).map((line) => ({
        material_id: line.material_id,
        purchase_request_line_id: line.id,
        quantity: line.remaining_quantity,
        unit_price: '0'
      })) ?? []
    }
  }

  async function convertPurchaseRequest(): Promise<void> {
    if (!window.nexora) return
    const form = requestConversionForm.value
    const lines = form.lines.filter((line) => Number(line.quantity) > 0)
    if (!form.requestId || !lines.length) return
    await perform(async () => {
      await window.nexora!.callApi('createPurchaseOrder', {
        purchase_request_id: form.requestId,
        supplier_id: form.supplier_id,
        reference: form.reference,
        lines: lines.map((line) => ({ ...line }))
      })
      selectRequestConversion(0)
    }, '采购订单草稿已由申请生成。')
  }

  function addLine(): void {
    receiptForm.value.lines.push({ material_id: 0, quantity: '1' })
  }

  function removeLine(index: number): void {
    if (receiptForm.value.lines.length > 1)
      receiptForm.value.lines.splice(index, 1)
  }

  async function createReceipt(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createReceipt', {
        supplier_id: receiptForm.value.supplier_id,
        warehouse_id: receiptForm.value.warehouse_id,
        purchase_order_id: receiptForm.value.purchase_order_id,
        reference: receiptForm.value.reference,
        lines: receiptForm.value.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity
        }))
      })
      receiptForm.value = {
        supplier_id: 0,
        warehouse_id: receiptForm.value.warehouse_id,
        purchase_order_id: null,
        reference: '',
        lines: [{ material_id: 0, quantity: '1' }]
      }
    }, '入库单草稿已创建，等待仓库员确认。')
  }

  function chooseReceiptOrder(): void {
    // 关联采购订单后使用订单供应商和待入库明细，数量仍允许操作员按本批次调整。
    const order = purchaseOrders.value.find(
      (item) => item.id === receiptForm.value.purchase_order_id
    )
    if (!order) {
      receiptForm.value.supplier_id = 0
      receiptForm.value.lines = [{ material_id: 0, quantity: '1' }]
      return
    }
    receiptForm.value.supplier_id = order.supplier_id
    receiptForm.value.lines = order.lines
      .filter((line) => Number(line.remaining_quantity) > 0)
      .map((line) => ({
        material_id: line.material_id,
        quantity: line.remaining_quantity
      }))
  }

  async function createPurchaseOrder(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createPurchaseOrder', {
        supplier_id: purchaseForm.value.supplier_id,
        reference: purchaseForm.value.reference,
        lines: purchaseForm.value.lines.map((line) => ({
          material_id: line.material_id,
          quantity: line.quantity,
          unit_price: line.unit_price, tax_rate: line.tax_rate, discount_rate: line.discount_rate, includes_tax: line.includes_tax
        }))
      })
      purchaseForm.value = {
        supplier_id: 0,
        reference: '',
        lines: [{ material_id: 0, quantity: '1', unit_price: '0' }]
      }
    }, '采购订单草稿已创建。')
  }

  async function confirmPurchaseOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('confirmPurchaseOrder', { orderId }),
      `采购订单 #${orderId} 已确认。`
    )
  }

  async function cancelPurchaseOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelPurchaseOrder', { orderId }),
      `采购订单 #${orderId} 已取消。`
    )
  }

  async function postReceipt(receiptId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postReceipt', { receiptId }),
      `入库单 #${receiptId} 已确认，库存流水已生成。`
    )
  }

  async function reverseReceipt(receiptId: number): Promise<void> {
    if (!window.nexora) return
    const reason = receiptReversalReasons.value[receiptId]?.trim() ?? ''
    // 页面只提交纠错原因；关联退货与库存可用量由服务端写事务核对。
    await perform(async () => {
      await window.nexora!.callApi('reverseReceipt', { receiptId, reason })
      delete receiptReversalReasons.value[receiptId]
    }, `入库单 #${receiptId} 已冲销，库存与应付已追加更正记录。`)
  }

  function choosePurchaseReturnReceipt(): void {
    const receipt = selectedPurchaseReturnReceipt.value
    // 原入库行决定退货上限和出库仓库，页面只预填当前尚可退的数量。
    purchaseReturnForm.value.lines =
      receipt?.lines
        .filter((line) => Number(line.returnable_quantity) > 0)
        .map((line) => ({
          receipt_line_id: line.id,
          quantity: line.returnable_quantity
        })) ?? []
  }

  async function createPurchaseReturn(): Promise<void> {
    if (!window.nexora || !purchaseReturnForm.value.lines.length) return
    await perform(async () => {
      await window.nexora!.callApi('createPurchaseReturn', {
        receipt_id: purchaseReturnForm.value.receipt_id,
        reason: purchaseReturnForm.value.reason,
        lines: purchaseReturnForm.value.lines.map((line) => ({ ...line }))
      })
      purchaseReturnForm.value = { receipt_id: 0, reason: '', lines: [] }
    }, '采购退货草稿已创建。')
  }

  async function submitPurchaseReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(() => window.nexora!.callApi('submitPurchaseReturn', { returnId }),
      `采购退货单 #${returnId} 已提交，仓库待确认出库。`)
  }

  async function postPurchaseReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postPurchaseReturn', { returnId }),
      `采购退货单 #${returnId} 已确认，原入库仓库库存已扣减。`
    )
  }

  async function cancelPurchaseReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelPurchaseReturn', { returnId }),
      `采购退货单 #${returnId} 已取消。`
    )
  }

  async function reversePurchaseReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    const reason = purchaseReturnReversalReasons.value[returnId]?.trim() ?? ''
    // 正向补回库存和应付更正均由服务端写事务完成，页面只提交纠错原因。
    await perform(async () => {
      await window.nexora!.callApi('reversePurchaseReturn', {
        returnId,
        reason
      })
      delete purchaseReturnReversalReasons.value[returnId]
    }, `采购退货单 #${returnId} 已冲销，原仓库存与应付已追加更正记录。`)
  }

  return {
    chooseGoodsReceiptOrder,
    createGoodsReceipt,
    confirmGoodsReceipt,
    cancelGoodsReceipt,
    editPurchaseRequest,
    savePurchaseRequest,
    submitPurchaseRequest,
    approvePurchaseRequest,
    rejectPurchaseRequest,
    cancelPurchaseRequest,
    selectRequestConversion,
    convertPurchaseRequest,
    addLine,
    removeLine,
    createReceipt,
    chooseReceiptOrder,
    createPurchaseOrder,
    confirmPurchaseOrder,
    cancelPurchaseOrder,
    postReceipt,
    reverseReceipt,
    choosePurchaseReturnReceipt,
    createPurchaseReturn,
    submitPurchaseReturn,
    postPurchaseReturn,
    cancelPurchaseReturn,
    reversePurchaseReturn
  }
}
