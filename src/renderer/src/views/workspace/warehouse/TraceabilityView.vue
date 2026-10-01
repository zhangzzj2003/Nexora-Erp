<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { ErpOperations } from '../../../../../shared/erp-api'
const store=usePiniaAppStore()
const { traceResult: result, user }=storeToRefs(store)
const query=ref<ErpOperations['queryTrace']['input']>({kind:'sales_order',id:0})
const busy=ref(false);const message=ref('');const orderId=ref(0)
const allocation=ref({work_order_id:0,reason:'',lines:[{sales_order_line_id:0,quantity:'1'}]})
const kinds: {value:ErpOperations['queryTrace']['input']['kind'];label:string}[]=[{value:'sales_order',label:'销售订单'},{value:'work_order',label:'生产工单'},{value:'shipment',label:'销售出库'},{value:'lot',label:'库存批次'},{value:'receipt',label:'采购入库'}]
const nodeColumns=[{key:'number',title:'单据／批次编号'},{key:'status',title:'状态'},{key:'reference',title:'业务参考号'},{key:'material_id',title:'物料编号'},{key:'warehouse_id',title:'仓库编号'},{key:'quantity',title:'流转数量'},{key:'basis',title:'追踪依据'},{key:'created_at',title:'建立时间'},{key:'warehouse_balances',title:'批次余额'}]
const edgeColumns=[{key:'from',title:'上游单据'},{key:'to',title:'下游单据'},{key:'quantity',title:'关联数量'},{key:'relation',title:'关系'}]
watch(()=>user.value?.id,()=>{result.value=null;allocation.value={work_order_id:0,reason:'',lines:[{sales_order_line_id:0,quantity:'1'}]};message.value=''})
async function execute(kind:'query'|'allocate'):Promise<void>{
  if(busy.value)return
  busy.value=true;message.value=''
  try{if(kind==='query')await store.queryTrace({...query.value});else{await store.allocateSalesWork({work_order_id:allocation.value.work_order_id,reason:allocation.value.reason,lines:allocation.value.lines.map(line=>({...line}))});message.value='销售需求分配已保存。'}}
  catch(error){message.value=error instanceof Error?error.message:'处理失败，请重试'}finally{busy.value=false}
}
</script>
<template>
  <section class="page-header"><h1>单据与批次溯源</h1><p>各步骤使用独立单号，以数量关系串联销售、工单、完工与出库。系统批次按先入先出分配；历史存量明确标注为待补录。</p></section>
  <form class="card" @submit.prevent="execute('query')"><div class="form-grid"><label>追踪起点<WorkspaceSelect v-model="query.kind" :options="kinds" /></label><label>编号<AppInput v-model.number="query.id" type="number" min="1" required /></label></div><div class="form-actions"><AppButton type="submit" :disabled="busy">追踪关联单据</AppButton></div></form>
  <p v-if="message" role="status">{{ message }}</p>
  <template v-if="result"><p>关联节点 {{ result.totals.nodes }} 个，数量关系 {{ result.totals.edges }} 条。</p><WorkspaceTable title="关联单据" :snapshot-id="result.snapshot_id" snapshot-path="nodes" :columns="nodeColumns" :data="result.nodes" :min-table-width="1300" /><WorkspaceTable title="数量与流转关系" :snapshot-id="result.snapshot_id" snapshot-path="edges" :columns="edgeColumns" :data="result.edges" /></template>
  <form v-if="store.can('work_order.create')" class="card" @submit.prevent="execute('allocate')"><h2>工单分配销售需求</h2><p>一个工单可分配多个销售明细；同一销售明细可拆给多个工单。留空的未分配产量用于备货。保存替换本工单全部分配，完成后不能修改。</p><div class="form-grid"><label>生产工单<WorkspaceSelect v-model="allocation.work_order_id" remote-dataset="workOrders" :remote-filters="{statuses:'draft,released'}" :options="[{value:0,label:'选择工单',disabled:true}]" required /></label><label>查找销售订单<WorkspaceSelect v-model="orderId" remote-dataset="salesOrders" :remote-filters="{statuses:'confirmed,partially_shipped,completed'}" :options="[{value:0,label:'选择订单',disabled:true}]" /></label><label>分配原因<AppInput v-model.trim="allocation.reason" maxlength="200" required /></label></div>
    <div v-for="(line,index) in allocation.lines" :key="index" class="form-grid"><label>销售明细编号<WorkspaceSelect v-model="line.sales_order_line_id" remote-dataset="salesOrderLines" :disabled="!orderId" :remote-filters="{sales_order_id:orderId}" :options="[{value:0,label:'先选择销售订单',disabled:true}]" required /></label><label>分配数量<AppInput v-model="line.quantity" required inputmode="decimal" /></label><AppButton type="button" variant="text" @click="allocation.lines.splice(index,1)">移除</AppButton></div>
    <div class="form-actions"><AppButton type="button" variant="secondary" @click="allocation.lines.push({sales_order_line_id:0,quantity:'1'})">添加分配</AppButton><AppButton type="submit" :disabled="busy">保存分配</AppButton></div>
  </form>
  <WorkspaceTable title="库存批次" dataset="inventoryLots" :columns="[{key:'id',title:'批次编号'},{key:'code',title:'系统批号'},{key:'material_id',title:'物料编号'},{key:'basis',title:'依据'}]" :data="[]" />
</template>
