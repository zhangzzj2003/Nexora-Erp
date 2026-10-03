import {watch} from 'vue'
import type {AppState} from '../state'
import type {InventoryWarningInput, InventoryWarningRow} from '../../../../shared/inventory-warning-api'
import {displayError} from '../../utils/formatters.ts'

export function emptyWarningForm(): InventoryWarningInput {
  return {warehouse_id:0, material_id:0, version:0, threshold:'', enabled:true, reason:''}
}
export function createInventoryWarningActions(state: AppState, perform:(run:()=>Promise<unknown>, message:string)=>Promise<void>) {
  let owner=0, reads=0, details=0, eventReads=0
  const can=(code:string)=>state.user.value?.permissions.includes(code)??false
  const available=()=>!!window.nexora && !state.connectionLost.value && can('inventory.view')
  function clearWarningDetail():void {details++;state.warningDetail.value=null}
  function invalidate():void {
    reads++;eventReads++;clearWarningDetail();state.warningOverview.value=null;state.warningLoading.value=false;state.warningError.value=''
    state.warningEvents.value=null;state.warningEventsLoading.value=false;state.warningEventsError.value=''
  }
  watch(()=>`${state.server.value?.id}:${state.server.value?.fingerprint}:${state.user.value?.id}:${state.user.value?.permissions.join('|')}`,()=>{
    owner++;invalidate();state.warningForm.value=emptyWarningForm();state.warningEditing.value=false;state.warningWarehouseId.value=0
  },{flush:'sync'})
  // 同账号断线保留阈值正文与修订版本，但失效旧数量和审计。
  watch(state.connectionLost,()=>{owner++;invalidate()},{flush:'sync'})
  async function loadInventoryWarnings():Promise<boolean> {
    if(!available())return false
    const ticket=++reads, session=owner, warehouse=state.warningWarehouseId.value
    state.warningLoading.value=true;state.warningError.value='';clearWarningDetail();state.warningOverview.value=null
    try {
      const result=await window.nexora!.callApi('inventoryWarnings',warehouse?{warehouseId:warehouse}:undefined)
      if(ticket!==reads || session!==owner || !available() || warehouse!==state.warningWarehouseId.value)return false
      if(result.warehouse_id!==(warehouse || null))throw Error('预警仓库范围不匹配，请重新读取。')
      state.warningOverview.value=result;return true
    } catch(error) {if(ticket===reads && session===owner)state.warningError.value=displayError(error);return false}
    finally {if(ticket===reads && session===owner)state.warningLoading.value=false}
  }
  async function loadWarningEvents(append=false):Promise<boolean> {
    if(!available())return false
    const warehouse=state.warningWarehouseId.value, previous=state.warningEvents.value
    if(append && (!previous || previous.warehouse_id!==(warehouse || null) || previous.next_before_id===null))return false
    const before=append ? previous!.next_before_id! : undefined
    const ticket=++eventReads, session=owner
    state.warningEventsLoading.value=true;state.warningEventsError.value=''
    if(!append)state.warningEvents.value=null
    try {
      const result=await window.nexora!.callApi('inventoryWarningEvents',{
        ...(warehouse?{warehouseId:warehouse}:{}),...(before?{beforeId:before}:{})})
      if(ticket!==eventReads || session!==owner || !available() || warehouse!==state.warningWarehouseId.value)return false
      if(result.warehouse_id!==(warehouse || null) || (before && result.events.some(event=>event.id>=before)))
        throw Error('预警事件来源范围不匹配，请重新读取。')
      state.warningEvents.value=append && previous ? {...result,events:[...previous.events,...result.events]} : result
      return true
    } catch(error) {if(ticket===eventReads && session===owner)state.warningEventsError.value=displayError(error);return false}
    finally {if(ticket===eventReads && session===owner)state.warningEventsLoading.value=false}
  }
  async function loadWarningDetail(row: Pick<InventoryWarningRow,'warehouse_id'|'material_id'>):Promise<boolean> {
    if(!available())return false
    clearWarningDetail();const ticket=details, session=owner;state.warningError.value=''
    try {
      const result=await window.nexora!.callApi('inventoryWarningDetail',{warehouse_id:row.warehouse_id,material_id:row.material_id})
      if(ticket!==details || session!==owner || !available())return false
      if(result.row.warehouse_id!==row.warehouse_id || result.row.material_id!==row.material_id)throw Error('预警证据来源不匹配，请重新读取。')
      state.warningDetail.value=result;return true
    } catch(error) {if(ticket===details && session===owner)state.warningError.value=displayError(error);return false}
  }
  function startWarningRule():boolean {
    if(!available() || !can('inventory_warning.manage') || state.busy.value)return false
    state.warningForm.value={...emptyWarningForm(),warehouse_id:state.warningWarehouseId.value}
    state.warningEditing.value=true;clearWarningDetail();state.error.value='';return true
  }
  async function editWarningRule(row: InventoryWarningRow):Promise<boolean> {
    if(!can('inventory_warning.manage') || !await loadWarningDetail(row))return false
    const latest=state.warningDetail.value?.row;if(!latest)return false
    state.warningForm.value={warehouse_id:latest.warehouse_id,material_id:latest.material_id,version:latest.version,
      threshold:latest.threshold,enabled:latest.enabled,reason:''}
    state.warningEditing.value=true;state.error.value='';return true
  }
  async function saveWarningRule():Promise<boolean> {
    if(!available() || !can('inventory_warning.manage') || state.busy.value)return false
    const session=owner, input={...state.warningForm.value};let saved=false
    await perform(async()=>{
      if(session!==owner || !available() || !can('inventory_warning.manage'))return
      const result=await window.nexora!.callApi('saveInventoryWarning',input)
      if(result.row.warehouse_id!==input.warehouse_id || result.row.material_id!==input.material_id)throw Error('保存结果来源不匹配，请刷新后核对。')
      if(session===owner && available() && can('inventory_warning.manage'))saved=true
    },'预警阈值与修订证据已保存；库存仍以已确认流水为准。')
    if(!saved || session!==owner || !available() || !can('inventory_warning.manage'))return false
    await loadInventoryWarnings()
    if(session===owner && available())await loadWarningDetail(input)
    if(session!==owner || !available() || !can('inventory_warning.manage'))return false
    state.warningForm.value=emptyWarningForm();state.warningEditing.value=false;return true
  }
  return {loadInventoryWarnings,loadWarningEvents,loadWarningDetail,clearWarningDetail,startWarningRule,editWarningRule,saveWarningRule}
}
