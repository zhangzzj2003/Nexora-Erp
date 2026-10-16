import { toRaw, watch } from 'vue'
import type { Bom, ProductionCostSettlement } from '../../../../shared/erp-api'
import { validateDocumentApprovalRecord } from '../../../../shared/document-approval-api.ts'
import { validateProductResult } from '../../../../shared/product-api.ts'
import { displayError } from '../../utils/formatters.ts'
import type { AppState } from '../state'
import type { WorkspaceRouteKey } from '../../router/workspace-routes'
import type {CompletionLotPartInput} from '../../../../shared/completion-lot-api'
import type {MaterialIssueLotLineInput,MaterialIssueLotOptions} from '../../../../shared/material-issue-lot-api'
import type {MaterialReturnLotLineInput,MaterialReturnLotOptions} from '../../../../shared/material-return-lot-api'
// 生产操作集中在业务模块；写入后仍由统一入口刷新服务端快照。
export function createProductionActions(
  state: AppState,
  perform: (action: () => Promise<unknown>, success: string) => Promise<void>,
  navigateToRoute: (key: WorkspaceRouteKey) => void
) {
  const {
    workOrders,
    materialIssues,
    materialReturns,
    productionCompletions,
    bomForm,
    workOrderForm,
    materialIssueForm,
    materialReturnForm,
    completionForm,
    inspectionDrafts,
    completionReversalReasons,
    materialValuationForm,
    productionChargeForm,
    costReversalReasons,
    productionSettlementForm,
    settlementReversalReasons
  } = state
  let bomCreateSession = 0, bomCreateTicket = 0
  watch(() => JSON.stringify([state.server?.value?.id, state.server?.value?.fingerprint, state.user?.value?.id,
    state.user?.value?.permissions.slice().sort(), state.connectionLost?.value]), () => {bomCreateSession++}, {flush:'sync'})
  async function createBom(): Promise<Bom | undefined> {
    const available = (): boolean => !!window.nexora && !state.connectionLost.value
      && !!state.user.value?.permissions.includes('bom.create')
    if (!available() || state.busy.value) return
    const session = bomCreateSession, ticket = ++bomCreateTicket, draft = bomForm.value
    const original = JSON.stringify(draft), bridge = window.nexora!
    const input = {
      product_material_id: draft.product_material_id,
      ...(draft.source_bom_id ? {source_bom_id: draft.source_bom_id} : {}),
      base_quantity: draft.base_quantity, note: draft.note, lines: draft.lines.map(line => ({...line}))
    }
    const sameSession = (): boolean => session === bomCreateSession && ticket === bomCreateTicket
      && available() && window.nexora === bridge
    const ownsDraft = (): boolean => sameSession() && bomForm.value === draft && JSON.stringify(bomForm.value) === original
    let created: Bom | undefined
    let confirmedForm: typeof bomForm.value | undefined, confirmedSnapshot = ''
    try {
      await perform(async () => {
        // perform 可能延迟执行回调，排队期间换账号、撤权或更换草稿后不能继续发旧请求。
        if (!ownsDraft()) throw Error('BOM 建档会话或草稿已变化，请重新确认。')
        const result = await bridge.callApi('createBom', input)
        if (!ownsDraft()) throw Error('BOM 建档会话或草稿已变化，请重新读取。')
        validateProductResult('bomDetail', result)
        if (result.status !== 'draft' || result.product_material_id !== input.product_material_id
          || (result.source_bom_id ?? null) !== (input.source_bom_id ?? null))
          throw Error('服务端返回了另一产品或来源的 BOM 草稿，请重新读取。')
        created = result
        // 合法回执已经确认建档成功；后续资料刷新失败也不能留下可重复提交的同一份原稿。
        const empty = {product_material_id:0,source_bom_id:null,base_quantity:'1',note:'',lines:[{component_material_id:0,quantity:'1'}]}
        const emptySnapshot = JSON.stringify(empty)
        bomForm.value = empty
        // 同步观察者可能立刻换账号或建立新草稿，只接管本次确实写入的空草稿。
        if (!sameSession()) throw Error('BOM 建档会话已变化，请重新读取。')
        if (toRaw(bomForm.value) === empty && JSON.stringify(bomForm.value) === emptySnapshot) {
          confirmedForm = bomForm.value; confirmedSnapshot = emptySnapshot
        }
      }, 'BOM 草稿已创建。')
    } catch (cause) {
      if (sameSession()) state.error.value = displayError(cause)
    }
    // 刷新、审批重读和 busy 解锁完成后再返回；新账号或新草稿不能被旧回执关闭或定位。
    if (!created || !sameSession() || !confirmedForm || bomForm.value !== confirmedForm
      || JSON.stringify(bomForm.value) !== confirmedSnapshot) return
    if (state.error.value) state.error.value = `BOM 草稿 #${created.id} 已保存，刷新资料失败：${state.error.value}`
    if (sameSession() && bomForm.value === confirmedForm && JSON.stringify(bomForm.value) === confirmedSnapshot) return created
  }

  async function activateBom(bomId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('activateBom', { bomId }),
      `BOM #${bomId} 已启用。`
    )
  }

  async function retireBom(bomId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('retireBom', { bomId }),
      `BOM #${bomId} 已停用。`
    )
  }

  async function cancelBom(bomId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelBom', { bomId }),
      `BOM #${bomId} 草稿已取消。`
    )
  }

  async function createWorkOrder(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createWorkOrder', {
        ...workOrderForm.value
      })
      // 成功后重置选择，避免误把下一张工单挂在旧版 BOM 上。
      workOrderForm.value = {
        bom_id: 0,
        warehouse_id: 1,
        target_quantity: '1',
        reference: '',
        note: ''
      }
    }, '生产工单草稿已创建，组件需求已固定。')
  }

  async function releaseWorkOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('releaseWorkOrder', { orderId }),
      `生产工单 #${orderId} 已下达。`
    )
  }

  async function cancelWorkOrder(orderId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelWorkOrder', { orderId }),
      `生产工单 #${orderId} 已取消。`
    )
  }

  function selectIssueOrder(orderId: number): void {
    const order = workOrders.value.find((item) => item.id === orderId)
    materialIssueForm.value = {
      work_order_id: orderId,
      warehouse_id: 1,
      reference: '',
      // 只预填仍需领用的组件，计划员可再调整本次分批数量。
      lines:
        order?.lines
          .filter((line) => Number(line.remaining_quantity) > 0)
          .map((line) => ({
            work_order_line_id: line.id,
            quantity: line.remaining_quantity
          })) ?? []
    }
    navigateToRoute('materialIssues')
  }

  async function createMaterialIssue(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createMaterialIssue', {
        ...materialIssueForm.value,
        lines: materialIssueForm.value.lines.map((line) => ({ ...line }))
      })
      materialIssueForm.value = {
        work_order_id: 0,
        warehouse_id: 1,
        reference: '',
        lines: []
      }
    }, '生产领料草稿已创建，确认前不会扣减库存。')
  }

  async function loadAvailableMaterialIssueLots(issueId: number): Promise<MaterialIssueLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('material_issue.post'))
      throw Error('当前账号无法读取生产领料批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableMaterialIssueLots', {issueId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('material_issue.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postMaterialIssue(issueId: number, lines?: MaterialIssueLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postMaterialIssue', { issueId, lines }),
      `生产领料单 #${issueId} 已确认，源仓库存已扣减。`
    )
  }

  async function cancelMaterialIssue(issueId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelMaterialIssue', { issueId }),
      `生产领料单 #${issueId} 草稿已取消。`
    )
  }

  async function reverseMaterialIssue(issueId: number, reason: string): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('reverseMaterialIssue', { issueId, reason }),
      `生产领料单 #${issueId} 已冲销，库存与工单可领量已按原单更正。`
    )
  }

  function selectReturnIssue(issueId: number): void {
    const issue = materialIssues.value.find((item) => item.id === issueId)
    materialReturnForm.value = {
      material_issue_id: issueId,
      reason: '',
      // 仅预填仍可退的领料明细；用户可按实际退回数量修改或移除。
      lines:
        issue?.lines
          .filter((line) => Number(line.returnable_quantity) > 0)
          .map((line) => ({
            material_issue_line_id: line.id,
            quantity: line.returnable_quantity
          })) ?? []
    }
    navigateToRoute('materialReturns')
  }

  async function createMaterialReturn(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createMaterialReturn', {
        ...materialReturnForm.value,
        lines: materialReturnForm.value.lines.map((line) => ({ ...line }))
      })
      materialReturnForm.value = {
        material_issue_id: 0,
        reason: '',
        lines: []
      }
    }, '生产退料草稿已创建，确认前不会增加库存。')
  }

  async function loadAvailableMaterialReturnLots(returnId: number): Promise<MaterialReturnLotOptions> {
    if (!window.nexora || state.connectionLost.value
        || !state.user.value?.permissions.includes('material_return.post'))
      throw Error('当前账号无法读取生产退料批次。')
    const owner = state.user.value.id
    const result = await window.nexora.callApi('availableMaterialReturnLots', {returnId})
    if (state.connectionLost.value || state.user.value?.id !== owner
        || !state.user.value.permissions.includes('material_return.post'))
      throw Error('连接或账号已变化，请重新读取批次。')
    return result
  }

  async function postMaterialReturn(returnId: number, lines?: MaterialReturnLotLineInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('postMaterialReturn', { returnId, lines }),
      `生产退料单 #${returnId} 已确认，组件已回到原领料仓库。`
    )
  }

  async function cancelMaterialReturn(returnId: number): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('cancelMaterialReturn', { returnId }),
      `生产退料单 #${returnId} 草稿已取消。`
    )
  }

  async function reverseMaterialReturn(returnId: number, reason: string): Promise<void> {
    if (!window.nexora) return
    await perform(
      () => window.nexora!.callApi('reverseMaterialReturn', {returnId, reason}),
      `生产退料单 #${returnId} 已冲销，组件重新计入工单净领料。`
    )
  }

  function selectCompletionOrder(orderId: number, navigate = true): void {
    const order = workOrders.value.find((item) => item.id === orderId)
    completionForm.value = {
      work_order_id: orderId,
      reported_quantity: order?.remaining_output_quantity ?? '1',
      reference: ''
    }
    // 页面内切换工单只更新草稿，保留从工单带来的列表范围与打开意图。
    if (navigate) navigateToRoute('productionCompletions')
  }

  async function createProductionCompletion(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('createProductionCompletion', {
        ...completionForm.value
      })
      completionForm.value = {
        work_order_id: 0,
        reported_quantity: '1',
        reference: ''
      }
    }, '完工报工草稿已创建，质检并确认前不会增加成品库存。')
  }

  async function inspectProductionCompletion(
    completionId: number
  ): Promise<void> {
    if (!window.nexora) return
    const draft = inspectionDrafts.value[completionId]
    if (!draft) return
    await perform(
      () =>
        window.nexora!.callApi('inspectProductionCompletion', {
          completionId,
          accepted_quantity: draft.accepted_quantity,
          qc_note: draft.qc_note
        }),
      `完工单 #${completionId} 的质检结果已记录。`
    )
  }

  async function postProductionCompletion(completionId: number,
                                          lots?: CompletionLotPartInput[]): Promise<void> {
    if (!window.nexora) return
    await perform(
      () =>
        window.nexora!.callApi('postProductionCompletion', { completionId, ...(lots ? {lots} : {}) }),
      `完工单 #${completionId} 已确认。`
    )
  }

  async function cancelProductionCompletion(
    completionId: number
  ): Promise<void> {
    if (!window.nexora) return
    await perform(
      () =>
        window.nexora!.callApi('cancelProductionCompletion', { completionId }),
      `完工单 #${completionId} 已取消。`
    )
  }

  async function reverseProductionCompletion(
    completionId: number
  ): Promise<void> {
    const reason = completionReversalReasons.value[completionId]?.trim()
    if (!reason) return
    await perform(
      () =>
        window.nexora!.callApi('reverseProductionCompletion', {
          completionId,
          reason
        }),
      `完工单 #${completionId} 已冲销，原记录和冲销凭据均已保留。`
    )
    delete completionReversalReasons.value[completionId]
  }

  async function recordMaterialValuation(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('recordMaterialValuation', {
        ...materialValuationForm.value
      })
      materialValuationForm.value = {
        material_issue_line_id: 0,
        unit_cost: '0',
        reference: '',
        note: ''
      }
    }, '领料明细核定单价已记录。')
  }

  async function recordProductionCharge(): Promise<void> {
    if (!window.nexora) return
    await perform(async () => {
      await window.nexora!.callApi('recordProductionCharge', {
        ...productionChargeForm.value
      })
      productionChargeForm.value = {
        work_order_id: 0,
        kind: 'labor',
        amount: '',
        reference: '',
        note: ''
      }
    }, '生产费用已归集到工单。')
  }

  async function reverseProductionCost(entryId: number): Promise<void> {
    if (!window.nexora) return
    const reason = costReversalReasons.value[entryId]?.trim()
    if (!reason) return
    await perform(async () => {
      await window.nexora!.callApi('reverseProductionCost', {
        entryId,
        reason
      })
      delete costReversalReasons.value[entryId]
    }, `成本记录 #${entryId} 已冲销，原记录仍可查询。`)
  }
  // 结算草稿和正式执行均保护队列归属；切服/换账号后不能继续发送旧请求。
  let settlementOwner = 0
  watch(() => `${state.server?.value?.id}:${state.server?.value?.fingerprint}:${state.user?.value?.id}:${state.user?.value?.roles?.join('|')}:${state.user?.value?.permissions.join('|')}`,
    () => { settlementOwner++ }, { flush:'sync' })
  const settlementAvailable = (permission: string) => !!window.nexora && !state.connectionLost?.value
    && !!state.user?.value?.permissions.includes(permission)
  function settlementGuard(session: number,permission: string): void {
    if (session!==settlementOwner || !settlementAvailable(permission)) throw Error('成本结算会话或授权已变化，请重新读取。')
  }
  async function settleProductionCost(): Promise<void> {
    if (!settlementAvailable('production_cost.settle')) return
    const session=settlementOwner,input={...productionSettlementForm.value}
    await perform(async () => {
      settlementGuard(session,'production_cost.settle')
      await window.nexora!.callApi('settleProductionCost',input)
      if(session!==settlementOwner)return
      productionSettlementForm.value = { work_order_id: 0, reference: '', note: '' }
    }, '预计结算草稿已保存，独立批准执行后才计价并锁定成本来源。')
  }

  async function changeProductionSettlementStatus(row:ProductionCostSettlement,action:'post'|'cancel',reason:string):Promise<void> {
    if (!settlementAvailable('production_cost.settle') || row.status!=='draft'
      || action==='post' && row.approval?.status!=='approved'
      || action==='cancel' && ['submitted','approved'].includes(row.approval?.status??''))return
    const session=settlementOwner
    await perform(async()=>{
      settlementGuard(session,'production_cost.settle')
      await window.nexora!.callApi('changeProductionSettlementStatus',{id:row.id,version:row.version,action,reason})
    },action==='post'?'成本已批准执行，正式分摊与来源锁定已生效。':'结算草稿已取消，未改变库存成本。')
  }

  async function reverseProductionSettlement(settlementId: number): Promise<void> {
    if (!settlementAvailable('production_cost.reopen')) return
    const session=settlementOwner
    await perform(async () => {
      settlementGuard(session,'production_cost.reopen')
      const approved=await window.nexora!.callApi('documentApproval',{document_type:'ProductionCostSettlement',document_id:settlementId,intent:'reverse'})
      settlementGuard(session,'production_cost.reopen');validateDocumentApprovalRecord(approved)
      if(approved.document_type!=='ProductionCostSettlement' || approved.document_id!==settlementId
        || approved.intent!=='reverse' || approved.status!=='approved' || !approved.content_matches)throw Error('请先完成成本结算独立冲销审批。')
      // 原因取自当次固定批准，不能把弹窗中新输入代替已批准的更正依据。
      await window.nexora!.callApi('reverseProductionSettlement',{settlementId,reason:approved.reversal_reason})
      if(session!==settlementOwner)return
      delete settlementReversalReasons.value[settlementId]
    }, '成本结算已独立批准冲销，可按新依据更正来源；原快照保留。')
  }
  return {
    createBom,
    activateBom,
    retireBom,
    cancelBom,
    createWorkOrder,
    releaseWorkOrder,
    cancelWorkOrder,
    selectIssueOrder,
    createMaterialIssue,
    postMaterialIssue,
    loadAvailableMaterialIssueLots,
    cancelMaterialIssue,
    reverseMaterialIssue,
    selectReturnIssue,
    createMaterialReturn,
    postMaterialReturn,
    loadAvailableMaterialReturnLots,
    cancelMaterialReturn,
    reverseMaterialReturn,
    selectCompletionOrder,
    createProductionCompletion,
    inspectProductionCompletion,
    postProductionCompletion,
    cancelProductionCompletion,
    reverseProductionCompletion,
    recordMaterialValuation,
    recordProductionCharge,
    reverseProductionCost,
    settleProductionCost,
    changeProductionSettlementStatus,
    reverseProductionSettlement
  }
}
