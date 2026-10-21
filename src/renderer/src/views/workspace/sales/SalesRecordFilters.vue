<script setup lang="ts">
import type {Customer} from '../../../../../shared/erp-api'
import type {SalesRecordFilters} from '../../../utils/sales-documents'
import {salesStatusLabels, newSalesFilters} from '../../../utils/sales-documents'
import {NDatePicker} from 'naive-ui'
import {datePickerString, vDateField} from '../../../utils/date-field'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
const model = defineModel<SalesRecordFilters>({required:true})
withDefaults(defineProps<{customers?: Customer[]; statuses: string[]}>(),{customers:()=>[]})
const emit = defineEmits<{clear: []}>()
// 三类销售单据共用筛选项，清空时连同所在页面的关键字一起恢复。
function clear(): void { model.value = newSalesFilters(); emit('clear') }
</script>
<template>
  <label>状态<WorkspaceSelect v-model="model.status" :options="[{label:'全部状态',value:''},...statuses.map(value=>({value,label:salesStatusLabels[value]}))]" /></label>
  <label>客户<WorkspaceSelect v-model="model.customer" :options="[{label:'全部客户',value:null},...customers.map(row=>({value:row.id,label:row.name}))]" /></label>
  <label>创建日期从<NDatePicker :formatted-value="model.from || null" type="date" clearable format="yyyy-MM-dd" value-format="yyyy-MM-dd"
    v-date-field="{required:false,min:'1900-01-01',max:model.to || '2199-12-31'}"
    @update:formatted-value="value=>model.from=datePickerString(value)" /></label>
  <label>至<NDatePicker :formatted-value="model.to || null" type="date" clearable format="yyyy-MM-dd" value-format="yyyy-MM-dd"
    v-date-field="{required:false,min:model.from || '1900-01-01',max:'2199-12-31'}"
    @update:formatted-value="value=>model.to=datePickerString(value)" /></label>
  <AppButton @click="clear">清空筛选</AppButton>
</template>
