<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { useLocalPagination } from '../../../composables/use-local-pagination'
import { displayError } from '../../../utils/formatters'
import type { MaterialUnit, MaterialUnitChange, MaterialUnitInput } from '../../../../../shared/material-unit-api'
import './catalog.css'

// 单位快照统一由 Pinia 管理，本页只保存筛选和未提交草稿。
const store = usePiniaAppStore()
const { materialUnits, busy, connectionLost } = storeToRefs(store)
const { can, saveMaterialUnit, localTime } = store
const query = ref('')
const status = ref('all')
const filtered = computed(() => materialUnits.value.filter(item =>
  (status.value === 'all' || item.enabled === (status.value === 'enabled'))
  && `${item.name} ${item.notes}`.toLowerCase().includes(query.value.trim().toLowerCase())))
const filterKey = computed(() => JSON.stringify([query.value, status.value]))
const {rows, total, page, pageSize, changePage} = useLocalPagination(filtered, filterKey)
const columns = [{key:'name',title:'单位名称'}, {key:'status',title:'状态',width:'120px'},
  {key:'material_count',title:'使用物料数',width:'150px'}, {key:'notes',title:'备注'}, {key:'actions',title:'操作',width:'210px'}]
const editingId = ref<number>()
const showForm = ref(false)
const loading = ref(false)
const detailError = ref('')
const referenced = ref(false)
const form = reactive<MaterialUnitInput>({name:'', enabled:true, notes:'', reason:''})
const auditOpen = ref(false)
const auditRows = ref<MaterialUnitChange[]>([])
const auditTitle = ref('')

async function edit(item?: MaterialUnit): Promise<void> {
  detailError.value = ''
  if (!item) {
    editingId.value = undefined
    referenced.value = false
    Object.assign(form, {name:'', enabled:true, notes:'', version:undefined, reason:''})
    showForm.value = true
    return
  }
  if (!window.nexora || connectionLost.value || loading.value) return
  const user = store.user, server = store.server
  loading.value = true
  try {
    // 编辑前读取新版本，避免另一客户端停用或改名后被旧列表覆盖。
    const latest = await window.nexora.callApi('materialUnitDetail', {id:item.id})
    if (store.user !== user || store.server !== server || connectionLost.value) return
    editingId.value = latest.id
    referenced.value = latest.material_count > 0
    Object.assign(form, {name:latest.name, enabled:latest.enabled, notes:latest.notes, version:latest.version, reason:''})
    showForm.value = true
  } catch (cause) { detailError.value = displayError(cause) }
  finally { loading.value = false }
}
async function save(): Promise<void> {
  if (await saveMaterialUnit({...form}, editingId.value)) showForm.value = false
}
async function history(item: MaterialUnit): Promise<void> {
  if (!window.nexora || loading.value || connectionLost.value) return
  const user = store.user, server = store.server
  loading.value = true
  detailError.value = ''
  try {
    const changes = await window.nexora.callApi('materialUnitChanges', {id:item.id})
    if (store.user !== user || store.server !== server || connectionLost.value) return
    auditRows.value = changes
    auditTitle.value = `${item.name} · 单位变更记录`
    auditOpen.value = true
  } catch (cause) { detailError.value = displayError(cause) }
  finally { loading.value = false }
}
</script>

<template>
  <section class="stack catalog-page">
    <WorkspaceTable :show-title="false" title="单位列表" :data="rows" :columns="columns" :min-table-width="760"
      :pagination="{page, pageSize, total, disabled:connectionLost}" @page-change="changePage">
      <template #actions>
        <AppButton v-if="can('catalog.manage')" type="button" variant="primary" :disabled="busy || connectionLost" @click="edit()">新增单位</AppButton>
      </template>
      <template #filters>
        <label class="catalog-search">搜索单位<AppInput v-model="query" placeholder="单位名称或备注" maxlength="120" /></label>
        <label class="material-category-filter">单位状态<WorkspaceSelect v-model="status" :options="[{value:'all',label:'全部状态'}, {value:'enabled',label:'启用'}, {value:'disabled',label:'停用'}]" aria-label="单位状态" /></label>
      </template>
      <template #beforeTable>
        <p v-if="detailError" role="alert">{{detailError}}</p>
        <NModal v-model:show="showForm" preset="card" :mask-closable="!busy"
          :style="{width:'min(680px, calc(100vw - 32px))', maxHeight:'calc(100vh - 48px)', overflowY:'auto'}">
          <form v-if="showForm && can('catalog.manage')" class="catalog-editor" @submit.prevent="save">
            <h3>{{editingId ? '编辑单位' : '新增单位'}}</h3>
            <p class="material-hint">停用后不再用于新选择，已使用该单位的物料保留原值。</p>
            <fieldset class="material-section" :disabled="busy || connectionLost">
              <legend>单位资料</legend>
              <div class="form-grid">
                <label>单位名称 *<AppInput v-model.trim="form.name" aria-label="单位名称" required maxlength="20" :readonly="referenced" placeholder="如：件、条、米" />
                  <span v-if="referenced" class="material-hint">已被物料使用的单位不能改名。</span>
                </label>
                <label>状态<WorkspaceSelect v-model="form.enabled" :options="[{value:true,label:'启用'}, {value:false,label:'停用'}]" aria-label="单位启用状态" /></label>
                <label class="supplier-wide">备注<AppInput v-model.trim="form.notes" aria-label="单位备注" maxlength="500" placeholder="如：用于线材长度计量" /></label>
                <label v-if="editingId" class="supplier-wide">修改原因 *<AppInput v-model.trim="form.reason" required aria-label="单位修改原因" maxlength="500" /></label>
              </div>
            </fieldset>
            <div class="form-actions">
              <AppButton type="submit" variant="primary" :disabled="busy || connectionLost">保存</AppButton>
              <AppButton type="button" variant="secondary" :disabled="busy" @click="showForm=false">取消</AppButton>
            </div>
          </form>
        </NModal>
        <NModal v-model:show="auditOpen" preset="card" :title="auditTitle"
          :style="{width:'min(760px, calc(100vw - 32px))', maxHeight:'calc(100vh - 48px)', overflowY:'auto'}">
          <p v-if="!auditRows.length">暂无人工变更记录，初始化目录不生成历史操作。</p>
          <div v-for="change in auditRows" :key="change.id" class="catalog-audit-item">
            <strong>{{change.before?.name || '新增'}} → {{change.after.name}}</strong>
            <span>状态：{{change.before ? (change.before.enabled ? '启用' : '停用') : '无'}} → {{change.after.enabled ? '启用' : '停用'}}</span>
            <span>备注：{{change.before?.notes || '无'}} → {{change.after.notes || '无'}}</span>
            <small>{{change.reason}} · {{change.changed_by_name}} · {{localTime(change.created_at)}}</small>
          </div>
        </NModal>
      </template>
      <template #cell-name="{row}">{{row.name}}</template>
      <template #cell-status="{row}">{{row.enabled ? '启用' : '停用'}}</template>
      <template #cell-material_count="{row}">{{row.material_count}}</template>
      <template #cell-notes="{row}">{{row.notes || '—'}}</template>
      <template #cell-actions="{row}">
        <div class="catalog-actions">
          <AppButton v-if="can('catalog.manage')" type="button" variant="text" :disabled="busy || loading || connectionLost" @click="edit(row)">编辑</AppButton>
          <AppButton type="button" variant="text" :disabled="loading || connectionLost" @click="history(row)">变更记录</AppButton>
        </div>
      </template>
      <template #empty>暂无匹配的单位。</template>
    </WorkspaceTable>
  </section>
</template>
