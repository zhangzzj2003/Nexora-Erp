import type {EquipmentChange,MaintenanceJobRecord,MaintenanceAction,EquipmentDowntime} from '../../../../../shared/equipment-api'
export const equipmentStatus={active:'启用',inactive:'停用',retired:'报废'}
export const maintenanceStatus={draft:'草稿',submitted:'待审核',approved:'待执行',rejected:'已驳回',in_progress:'执行中',reported:'待验收',accepted:'已验收',cancelled:'已取消',reversed:'验收已更正'}
export const maintenanceKind={preventive:'周期保养',corrective:'故障维修'}
export const maintenanceCommand={submit:'提交审核',approve:'批准维护',reject:'驳回维护',start:'开始维护',report:'登记报工',rework:'退回重做',accept:'验收维护',cancel:'取消维护',reverse:'更正验收'}
export const partsStatus={draft:'待仓库确认',posted:'已确认领用',cancelled:'草稿已取消',reversed:'出库已冲销',missing:'原出库缺失'}
export function maintenanceActions(row:MaintenanceJobRecord,permissions:readonly string[]):MaintenanceAction[]{
  if(!permissions.includes('equipment.view'))return []
  const operations:Partial<Record<MaintenanceAction,string>>={approve:'review',reject:'review',start:'execute',report:'execute',rework:'accept'}
  return row.allowed_actions.filter(action=>permissions.includes('equipment.'+(operations[action]??action))
    && (action!=='start' || !row.parts.length || permissions.includes('other_outbound.create')))
}
export function downtimeLabel(row:EquipmentDowntime):string{
  const minutes=Math.floor(row.seconds/60)
  return `${Math.floor(minutes/60)} 小时 ${minutes%60} 分${row.ongoing?'（截至本次读取）':''}`
}
const names:Record<string,string>={code:'设备编号',name:'设备名称',serial_number:'序列号',location:'位置',status:'状态',
  reference:'依据编号',equipment_id:'设备',kind:'维护方式',plan_id:'周期计划',plan_version:'计划版本',plan_due_date:'本次到期日',
  work_order_id:'关联生产工单',assigned_to:'执行人',request_note:'维护要求',warehouse_id:'耗材仓库',parts_outbound_id:'耗材出库单',
  solution:'处理结果',labor_hours:'实际工时',service_amount:'声明外委费用（元）',interval_days:'间隔天数',next_due:'下次到期日',
  hour_plan_id:'运行小时计划',interval_hours:'间隔运行小时',next_due_hours:'下次到期表计小时',plan_due_hours:'本次小时阈值',
  plan_meter_reading_id:'建单表计证据',
  enabled:'计划启停',version:'版本',equipment_json:'设备快照',parts_json:'耗材明细'}
function value(key:string,entry:unknown):string{
  if(entry===null || entry===undefined || entry==='')return '未登记'
  if(key==='status')return maintenanceStatus[entry as keyof typeof maintenanceStatus]??equipmentStatus[entry as keyof typeof equipmentStatus]??String(entry)
  if(key==='kind')return maintenanceKind[entry as keyof typeof maintenanceKind]??String(entry)
  if(key==='enabled')return entry?'启用':'停用'
  if(key==='parts_json' || key==='equipment_json'){
    try{
      const parsed=JSON.parse(String(entry)) as unknown
      if(key==='parts_json' && Array.isArray(parsed))return parsed.map(row=>`物料 #${row.material_id} × ${row.quantity}`).join('；')||'无耗材'
      if(key==='equipment_json' && parsed && typeof parsed==='object'){
        const row=parsed as Record<string,unknown>;return `${row.code} · ${row.name} · ${row.location||'未登记位置'} · ${row.serial_number||'无序列号'}`
      }
    }catch{return '快照格式异常，请联系管理员'}
  }
  return String(entry)
}
export function equipmentChanges(change:EquipmentChange):{name:string;before:string;after:string}[]{
  return Object.entries(names).filter(([key])=>change.before?.[key]!==change.after[key] && (key in change.after || key in (change.before??{})))
    .map(([key,name])=>({name,before:value(key,change.before?.[key]),after:value(key,change.after[key])}))
}
export function maintenanceEffect(action:MaintenanceAction):string{
  if(action==='start')return '开始后登记停机；有耗材时只生成其他出库草稿，须由仓库另行确认才扣库存。'
  if(action==='report')return '登记处理结果、实际工时及声明外委费用；费用也须明确填零，不自动形成应付或总账凭证。有耗材须先确认出库。'
  if(action==='accept')return '验收须独立于编制、提交和执行人员。验收结束停机，周期保养按验收 UTC 日期加间隔天数推进计划。'
  if(action==='rework')return '退回指定执行人重新处理，继续原停机区间，之前报工证据保留。'
  if(action==='reverse')return '保留真实停机与耗材领用；仅在计划未被后续修订或工单使用时恢复原到期日，否则保留较新安排。实物更正须由仓库另行处理。'
  if(action==='cancel')return '关联耗材出库草稿须先取消；已实际领用的耗材不会自动归库。已开始的停机区间在取消时结束。'
  if(action==='approve' || action==='reject')return '核对设备、计划、执行人和耗材。编制、修订或提交人不得审核，包括管理员。'
  return '提交后不能修改正文；周期保养须到期，设备、计划版本及指定执行人须仍有效。'
}
