<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { CrmKind } from '../../../../../shared/crm-api'
import AppButton from '../../../components/app/AppButton.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import type { WorkspaceTableColumn } from '../../../utils/table-columns'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import { usePiniaAppStore } from '../../../store/app-store'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import { crmCustomerRows } from './crm-customers'
import { crmActivityLabel } from './crm-display'

defineProps<{ disabled: boolean }>()
const emit = defineEmits<{
  create: [kind: CrmKind, customerId: number]
  detail: [kind: CrmKind, id: number]
  records: [kind: CrmKind, customerId: number]
  assign: [customerId: number]
  import: []
}>()
const store = usePiniaAppStore()
const { crmOptions: options, crmOverview: overview, crmLoading: loading, user, server } = storeToRefs(store)
const query = ref(''), summary = ref(''), selectedId = ref(0)
const customers = computed(() => crmCustomerRows(options.value, overview.value))
const selected = computed(() => customers.value.find(row => row.id === selectedId.value))
// 归属转交或切换会话后立即退出旧客户，避免重新分配编号时恢复旧的客户详情。
watch(() => [user.value?.id, server.value?.id], () => { selectedId.value = 0; query.value = ''; summary.value = '' })
watch(customers, rows => { if (!rows.some(row => row.id === selectedId.value)) selectedId.value = 0 })
const counts = computed(() => [
  { key: '', label: '全部客户', count: customers.value.length },
  { key: 'pending', label: '待跟进客户', count: customers.value.filter(row => row.pending_count).length },
  { key: 'overdue', label: '跟进逾期', count: customers.value.filter(row => row.overdue_count).length, tone: 'danger' as const },
].map(row => ({ ...row, hint: '按当前可见客户统计，点击筛选客户' })))
const records = computed(() => customers.value.filter(row =>
  (!summary.value || (summary.value === 'pending' ? row.pending_count : row.overdue_count)) &&
  [row.name, row.owner_name, ...row.contacts.flatMap(contact => [contact.name, contact.phone, contact.email])]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const { rows, page, pageSize, total, changePage } = useLocalPagination(records, computed(() => `${query.value}:${summary.value}`))
// 客户列表缩减宽度，窄窗中固定操作列，避免“查看”被横向滚动遮住。
const columns: WorkspaceTableColumn[] = [
  { key: 'name', title: '客户名称', width: '220' }, { key: 'owner_name', title: '负责人', width: '120' },
  { key: 'contact_count', title: '联系人', width: '90' }, { key: 'pending', title: '待跟进', width: '150' },
  { key: 'next', title: '下次跟进', width: '230' }, { key: 'actions', title: '操作', width: '90', fixed: 'right' },
]
const activityRows = computed(() => [...(selected.value?.activities ?? [])].sort((a, b) =>
  Number(b.status === 'planned') - Number(a.status === 'planned') || b.id - a.id))
</script>
<template>
  <section class="stack crm-customers">
    <Teleport defer to="#workspace-page-summary"><WorkspaceSummaryFilters v-model="summary" :options="counts" @update:model-value="selectedId=0" /></Teleport>
    <WorkspaceTable v-if="!selected" title="客户" :show-title="false" :columns="columns" :data="rows" :min-table-width="900" :loading="loading" :pagination="{page,pageSize,total}" @page-change="changePage">
      <template #filters><WorkspaceSearchFilters v-model:query="query" :filters="{}" search-label="搜索客户" search-placeholder="客户、联系人或电话" :reset-disabled="!query && !summary" @reset="query='';summary=''" /></template>
      <template #actions>
        <AppButton :disabled="disabled" @click="store.loadCrm()">刷新</AppButton>
        <AppButton v-if="store.can('crm_contact.manage')" :disabled="disabled" @click.capture="captureDialogOrigin('ContactImportDialog:import',$event)" @click="emit('import')">导入联系人</AppButton>
        <AppButton v-if="store.can('customer.manage')" variant="primary" :disabled="disabled" @click="store.navigateToRoute('customers')">维护客户资料</AppButton>
      </template>
      <template #cell-name="{row}"><AppButton variant="text" :disabled="disabled" @click="selectedId=row.id">{{ row.name }}</AppButton></template>
      <template #cell-pending="{row}"><AppButton v-if="row.pending_count" variant="text" :disabled="disabled" @click="emit('records','activity',row.id)">{{ row.pending_count }} 项<span v-if="row.overdue_count"> · {{ row.overdue_count }} 项逾期</span></AppButton><span v-else>—</span></template>
      <template #cell-next="{row}"><template v-if="row.next_followup">{{ row.next_followup.due_date }}<span class="crm-secondary">{{ row.next_followup.subject }}</span></template><span v-else>暂无安排</span></template>
      <template #cell-actions="{row}"><AppButton size="small" :disabled="disabled" @click="selectedId=row.id">查看</AppButton></template>
      <template #empty>{{ query || summary ? '没有符合条件的客户。' : '暂无可见客户，请先维护客户资料或分配负责人。' }}</template>
    </WorkspaceTable>
    <template v-else>
      <section class="customer-heading card">
        <div><AppButton variant="text" :disabled="disabled" @click="selectedId=0">返回客户列表</AppButton><h2>{{ selected.name }}</h2><p class="muted">负责人：{{ selected.owner_name }}</p></div>
        <div class="crm-toolbar">
          <AppButton v-if="store.can('customer.assign')" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:owner',$event)" @click="emit('assign',selected.id)">分配负责人</AppButton>
          <AppButton :disabled="disabled" @click="emit('records','opportunity',selected.id)">商机管理</AppButton>
          <AppButton :disabled="disabled" @click="emit('records','quote',selected.id)">查看报价</AppButton>
          <AppButton v-if="store.can('crm_quote.create')" variant="primary" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:contact',$event)" @click="emit('create','quote',selected.id)">新建报价</AppButton>
        </div>
      </section>
      <WorkspaceTable title="联系人" :data="selected.contacts" :columns="[{key:'name',title:'姓名',width:'180'},{key:'job_title',title:'职务',width:'140'},{key:'phone',title:'电话',width:'180'},{key:'email',title:'邮箱',width:'220'},{key:'status',title:'状态',width:'100'},{key:'actions',title:'操作',width:'100',fixed:'right'}]" :min-table-width="900" actions-placement="heading">
        <template #actions><AppButton v-if="store.can('crm_contact.manage')" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:contact',$event)" @click="emit('create','contact',selected.id)">添加联系人</AppButton></template>
        <template #cell-status="{row}"><AppStatusTag :label="row.is_active?'启用':'停用'" :tone="row.is_active?'success':'neutral'" /></template>
        <template #cell-actions="{row}"><AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('crm-business-detail',$event)" @click="emit('detail','contact',row.id)">查看</AppButton></template>
        <template #empty>尚未添加联系人。</template>
      </WorkspaceTable>
      <WorkspaceTable title="跟进记录" :data="activityRows" :columns="[{key:'subject',title:'跟进事项',width:'300'},{key:'owner_name',title:'负责人',width:'130'},{key:'due_date',title:'期限',width:'160'},{key:'status',title:'状态',width:'130'},{key:'actions',title:'操作',width:'100',fixed:'right'}]" :min-table-width="850" actions-placement="heading">
        <template #actions><AppButton v-if="store.can('crm_activity.manage')" :disabled="disabled" @click.capture="captureDialogOrigin('CustomerRelationsView:contact',$event)" @click="emit('create','activity',selected.id)">安排跟进</AppButton></template>
        <template #cell-status="{row}"><AppStatusTag :label="row.overdue?'已逾期':crmActivityLabel[row.status as keyof typeof crmActivityLabel]" :tone="row.overdue?'danger':row.status==='completed'?'success':'neutral'" /></template>
        <template #cell-actions="{row}"><AppButton size="small" :disabled="disabled" @click.capture="captureDialogOrigin('crm-business-detail',$event)" @click="emit('detail','activity',row.id)">查看</AppButton></template>
        <template #empty>尚无跟进安排。</template>
      </WorkspaceTable>
    </template>
  </section>
</template>
<style scoped>
/* 客户详情沿用工作台卡片与表格，只增加标题区的响应式排列。 */
.customer-heading { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:20px; }
.customer-heading h2 { margin:12px 0 6px; font-size:20px; }
.customer-heading p { margin:0; }
.crm-toolbar { display:flex; flex-wrap:wrap; gap:8px; }
.crm-secondary { display:block; margin-top:4px; color:var(--workspace-field-muted); font-size:12px; }
</style>
