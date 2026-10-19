// 仅供自动测试与隔离浏览器验收，不含真实业务数据。
export const planApproval = (status = 'approved') => ({status,version:2,generation:1,current_step:1,
  steps:[{name:'批准',role:null}],policy_version:1,submitted_by:1,submitted_at:'2026-10-19 01:00:00',executed_by:null,executed_at:null})
export const planFixture = () => ({id:1,document_no:'SCJH-20261019-000001',version:1,reference:'十月智能控制器备货',note:'优先安排交付批次',reason:'按销售交付与备货编排',status:'draft',
  created_by:1,created_at:'2026-10-19 01:00:00',approval:planApproval(),progress:'unreleased',can_edit:false,line_count:1,overdue_count:0,
  start_date:'2026-10-20',end_date:'2026-10-25',products:'智能控制器',lines:[{id:1,plan_id:1,position:0,bom_id:1,bom_version:2,warehouse_id:1,warehouse_name:'主仓库',sales_order_line_id:null,sales_order_id:null,sales_reference:'',
    material_id:1,sku:'CTRL-001',name:'智能控制器',unit:'台',quantity:'100.000',start_date:'2026-10-20',end_date:'2026-10-25',priority:'high',released_quantity:'0.000',unreleased_quantity:'100.000',
    reported_quantity:'0.000',accepted_quantity:'0.000',rejected_quantity:'0.000',remaining_quantity:'100.000',overdue:false}],releases:[],changes:[{id:1,action:'create',reason:'按销售交付与备货编排',changed_by:1,created_at:'2026-10-19 01:00:00',before:null,after:{}}]})
export const planOptionsFixture = () => ({today:'2026-10-19',boms:[{id:1,material_id:1,version:2,base_quantity:'1',sku:'CTRL-001',name:'智能控制器',unit:'台',components:[{material_id:2,quantity:'2',component_bom_id:null}]}],
  materials:[{id:1,sku:'CTRL-001',name:'智能控制器',unit:'台'}],warehouses:[{id:1,code:'MAIN',name:'主仓库',version:1}],sales_lines:[]})
export const planInputFixture = () => ({reference:'十月生产计划',note:'首批生产',reason:'核对备货数量',lines:[{bom_id:1,warehouse_id:1,sales_order_line_id:null,quantity:'10',start_date:'2026-10-20',end_date:'2026-10-25',priority:'normal'}]})
