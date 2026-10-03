// 先校验服务端边界，再让页面把阶段、金额及可执行动作当作业务事实。
type Check=(value:unknown)=>boolean
const object=(value:unknown):value is Record<string,unknown>=>!!value && typeof value==='object' && !Array.isArray(value)
const text:Check=value=>typeof value==='string'
const id:Check=value=>typeof value==='number' && Number.isSafeInteger(value) && value>0
const flag:Check=value=>typeof value==='boolean'
const nullable=(check:Check):Check=>value=>value===null || check(value)
const array=(check:Check):Check=>value=>Array.isArray(value) && value.every(check)
const choice=(values:readonly unknown[]):Check=>value=>values.includes(value)
const decimal:Check=value=>typeof value==='string' && /^\d+(?:\.\d+)?$/.test(value)
const nonnegative:Check=value=>typeof value==='number' && Number.isSafeInteger(value) && value>=0
function fields(value:unknown,spec:Record<string,Check>):boolean{return object(value) && Object.entries(spec).every(([key,check])=>check(value[key]))}
const actions=['submit','approve','reject','start','report','rework','accept','cancel','reverse']
const audit:Check=value=>fields(value,{id,action:text,reason:text,evidence:text,changed_by:id,changed_by_name:text,created_at:text,before:nullable(object),after:object})
const downtime:Check=value=>fields(value,{id,equipment_id:id,job_id:id,started_at:text,ended_at:nullable(text),close_reason:text,started_by:id,
  ended_by:nullable(id),started_by_name:text,ended_by_name:nullable(text),seconds:nonnegative,ongoing:flag})
const base={id,version:id,created_by:id,created_at:text,changes:array(audit)}
const reading:Check=value=>fields(value,{id,equipment_id:id,hours:decimal,reference:text,reason:text,
  previous_reading_id:nullable(id),correction:flag,recorded_by:id,recorded_by_name:text,recorded_at:text})
const asset:Check=value=>fields(value,{...base,code:text,name:text,serial_number:text,location:text,status:choice(['active','inactive','retired']),
  running_job_ids:array(id),downtimes:array(downtime),meter_reading:nullable(reading),meter_readings:array(reading)})
const plan:Check=value=>fields(value,{...base,equipment_id:id,reference:text,title:text,interval_days:id,next_due:text,enabled:flag,due:flag,open_job_ids:array(id)})
const hourPlan:Check=value=>fields(value,{...base,equipment_id:id,reference:text,title:text,interval_hours:decimal,
  next_due_hours:decimal,current_hours:nullable(decimal),current_reading_id:nullable(id),enabled:flag,due:flag,open_job_ids:array(id)})
const part:Check=value=>fields(value,{material_id:id,quantity:decimal})
const roll:Check=value=>object(value) && (value.before===undefined || object(value.before)) && (value.after===undefined || object(value.after))
  && (value.reading_id===undefined || id(value.reading_id))
  && (value.reversal_effect===undefined || choice([null,'restored_due','retained_newer_schedule'])(value.reversal_effect))
const job:Check=value=>fields(value,{...base,reference:text,equipment_id:id,kind:choice(['preventive','corrective']),plan_id:nullable(id),
  hour_plan_id:nullable(id),plan_version:nullable(id),plan_due_date:nullable(text),plan_due_hours:nullable(decimal),
  plan_meter_reading_id:nullable(id),work_order_id:nullable(id),assigned_to:id,request_note:text,warehouse_id:nullable(id),parts:array(part),
  status:choice(['draft','submitted','approved','rejected','in_progress','reported','accepted','cancelled','reversed']),equipment_snapshot:object,
  work_order_snapshot:nullable(object),work_order_linked:flag,work_order_current_status:nullable(text),parts_outbound_id:nullable(id),
  parts_status:choice([null,'draft','posted','cancelled','reversed','missing']),solution:text,labor_hours:nullable(decimal),service_amount:nullable(decimal),
  plan_roll:roll,created_by_name:text,assigned_to_name:text,author_ids:array(id),reviewed_by:nullable(id),reported_by:nullable(id),accepted_by:nullable(id),
  started_at:nullable(text),reported_at:nullable(text),accepted_at:nullable(text),allowed_actions:array(choice(actions)),can_edit:flag,downtime:nullable(downtime)})
const overview:Check=value=>fields(value,{as_of:text,equipment:array(asset),plans:array(plan),hour_plans:array(hourPlan),jobs:array(job),
  executors:array(value=>fields(value,{id,username:text})),materials:array(value=>fields(value,{id,sku:text,name:text,unit:text})),
  warehouses:array(value=>fields(value,{id,name:text})),work_orders:array(value=>fields(value,{id,status:text,target_quantity:decimal}))})
export function validateEquipmentResult(action:string,value:unknown):void{
  const check=({equipmentOverview:overview,equipmentDetail:asset,maintenancePlanDetail:plan,maintenanceJobDetail:job,
    maintenanceHourPlanDetail:hourPlan,recordEquipmentMeter:reading,
    saveEquipment:asset,saveMaintenancePlan:plan,saveMaintenanceHourPlan:hourPlan,
    saveMaintenanceJob:job,changeMaintenanceJob:job} as Record<string,Check>)[action]
  if(check && !check(value))throw new Error('设备维护响应格式不匹配，请核对桌面端与服务端版本后重新读取。')
}
