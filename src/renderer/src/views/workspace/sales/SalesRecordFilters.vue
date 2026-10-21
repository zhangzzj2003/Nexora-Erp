<script setup lang="ts">
import { computed } from 'vue'
import type {Customer} from '../../../../../shared/erp-api'
import type {SalesRecordFilters} from '../../../utils/sales-documents'
import {salesStatusLabels, newSalesFilters} from '../../../utils/sales-documents'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import type {WorkspaceSearchFilterField} from '../../../utils/workspace-search-filters'
const model = defineModel<SalesRecordFilters>({required:true})
const query = defineModel<string>('query',{required:true})
const props=withDefaults(defineProps<{customers?:Customer[];statuses:string[];searchLabel:string}>(),{customers:()=>[]})
const fields=computed<WorkspaceSearchFilterField[]>(()=>[
  {kind:'select',key:'status',label:'状态',options:[{label:'全部状态',value:''},...props.statuses.map(value=>({value,label:salesStatusLabels[value]}))]},
  {kind:'select',key:'customer',label:'客户',options:[{label:'全部客户',value:null},...props.customers.map(row=>({value:row.id,label:row.name}))]},
  {kind:'date',key:'from',label:'创建日期从',maxKey:'to'}, {kind:'date',key:'to',label:'创建日期至',minKey:'from'},
])
// 复用已经打磨的查询控件；精确状态与概览互斥，避免相互抵消而出现空表。
function update(value:SalesRecordFilters):void {model.value={...value,group:value.status!==model.value.status?'':value.group}}
function reset():void {model.value=newSalesFilters();query.value=''}
</script>
<template>
  <WorkspaceSearchFilters v-model:query="query" :filters="model" :fields="fields" :search-label="searchLabel" search-placeholder="单号、客户或物料"
    :reset-disabled="!query && !model.status && !model.group && !model.customer && !model.from && !model.to"
    :issue="model.from && model.to && model.from>model.to?'开始日期不能晚于结束日期。':''" @update:filters="update" @reset="reset" />
</template>
