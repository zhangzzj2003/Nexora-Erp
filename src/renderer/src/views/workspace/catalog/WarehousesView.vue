<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, reactive, ref , watch, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import {  NPopconfirm } from 'naive-ui'
import type { Warehouse, WarehouseChange } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError } from '../../../utils/formatters'
import './catalog.css'

const store = usePiniaAppStore()
const { busy, connectionLost, warehouses } = storeToRefs(store)
const { can, saveWarehouse, deleteWarehouse, localTime } = store
const query = ref('')
const editingId = ref<number | undefined>()
const showForm = ref(false)
const form = reactive({ code: '', name: '', version: 0, reason: '' })
const detailLoading = ref(false)
const detailError = ref('')
const auditOpen = ref(false)
const auditLoading = ref(false)
const auditError = ref('')
const auditRows = ref<WarehouseChange[]>([])
const auditHasMore = ref(false)
const filtered = computed(() =>
  warehouses.value.filter((item) =>
    [item.code, item.name].join(' ').toLowerCase().includes(query.value.trim().toLowerCase())
  )
)
// 列头和空状态由公共组件渲染，仓库限制仍在页面操作中判断。
const columns = [
  { key: 'code', title: '仓库编码' },
  { key: 'name', title: '仓库名称' },
  { key: 'actions', title: '操作' }
]
// 等待期间只保留打开意图；取消与切页递增代次，迟到结果不能重开弹窗。
let formRead = 0
let auditRead = 0
const dialogSession = computed(() => `${store.server?.id}:${store.server?.fingerprint}:${store.user?.id}:${store.user?.permissions.join('|')}`)
watch(showForm, value => { if (!value) { formRead++; detailLoading.value = false } }, { flush: 'sync' })
watch(auditOpen, value => { if (!value) { auditRead++; auditLoading.value = false } }, { flush: 'sync' })
watch(dialogSession, () => { formRead++; auditRead++; showForm.value = false; auditOpen.value = false }, { flush: 'sync' })
onUnmounted(() => { formRead++; auditRead++ })
async function edit(item?: Warehouse): Promise<void> {
  const ticket = ++formRead
  detailError.value = ''
  if (!item) {
    detailLoading.value = false
    editingId.value = undefined
    Object.assign(form, { code: '', name: '', version: 0, reason: '' })
    showForm.value = true
    return
  }
  if (!window.nexora || connectionLost.value) return
  const session = dialogSession.value
  detailLoading.value = true
  showForm.value = true
  try {
    const latest = await window.nexora.callApi('warehouseDetail', { id: item.id })
    if (ticket !== formRead || !showForm.value || session !== dialogSession.value || connectionLost.value) return
    editingId.value = item.id
    Object.assign(form, { code: latest.code, name: latest.name, version: latest.version, reason: '' })
  } catch (cause) {
    if (ticket === formRead) detailError.value = displayError(cause)
  } finally {
    if (ticket === formRead) detailLoading.value = false
  }
}
async function save(): Promise<void> {
  if (await saveWarehouse({ ...form }, editingId.value)) showForm.value = false
}
async function loadAudit(more = false): Promise<void> {
  if (!window.nexora || auditLoading.value || connectionLost.value) return
  const session = dialogSession.value
  const ticket = ++auditRead
  auditError.value = ''
  auditLoading.value = true
  try {
    const rows = await window.nexora.callApi('recentWarehouseChanges',
      more && auditRows.value.length ? { before_id: auditRows.value[auditRows.value.length - 1].id } : {})
    if (ticket !== auditRead || !auditOpen.value || session !== dialogSession.value || connectionLost.value) return
    auditRows.value = more ? [...auditRows.value, ...rows] : rows
    auditHasMore.value = rows.length === 100
  } catch (cause) {
    if (ticket === auditRead) auditError.value = displayError(cause)
  } finally {
    if (ticket === auditRead) auditLoading.value = false
  }
}
function openAudit(): void {
  auditRows.value = []
  auditOpen.value = true
  void loadAudit()
}
</script>

<template>
  <section class="stack catalog-page">
    <!-- 主标题和说明统一由工作台外壳展示。 -->
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="仓库列表"
      :columns="columns"
      :min-table-width="440"
    >
      <template #actions>
        <AppButton
          v-if="can('warehouse.manage')"
          :disabled="busy || connectionLost"
          @click.capture="captureDialogOrigin('WarehousesView:form', $event)" @click="edit()"
          variant="primary"
          type="button"
          >新增仓库</AppButton
        >
        <AppButton type="button" variant="secondary" :disabled="connectionLost || auditLoading"
          @click.capture="captureDialogOrigin('WarehousesView:audit', $event)" @click="openAudit">变更记录</AppButton>
      </template>
      <template #filters>
        <label class="catalog-search"
          >搜索仓库<AppInput v-model="query" placeholder="输入名称或编码搜索"
        /></label>
        <span class="muted">共 {{ warehouses.length }} 条</span>
      </template>
      <template #beforeTable>
        <p v-if="detailError" role="alert">{{ detailError }}</p>
        <AppModal :busy="busy" origin-key="WarehousesView:form" @invalidated="showForm = false" :ready="!detailLoading" :load-error="detailError"
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="showForm && can('warehouse.manage')"
            class="catalog-editor"
            @submit.prevent="save"
          >
            <h3>{{ editingId ? '编辑仓库' : '新增仓库' }}</h3>
            <div class="form-grid">
              <label
                >仓库编码<AppInput
                  v-model.trim="form.code"
                  required
                  maxlength="40"
                  pattern="[A-Za-z0-9_-]+"
              /></label>
              <label>仓库名称<AppInput v-model.trim="form.name" required maxlength="80" /></label>
              <label v-if="editingId">修改原因<AppInput v-model.trim="form.reason" required maxlength="500" /></label>
            </div>
            <div class="form-actions">
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存</AppButton
              ><AppButton
                type="button"
                :disabled="busy"
                @click="showForm = false"
                variant="secondary"
                >取消</AppButton
              >
            </div>
          </form>
        </AppModal>
        <AppModal :busy="busy" origin-key="WarehousesView:audit" @invalidated="auditOpen = false" :ready="!auditLoading" :load-error="auditError" v-model:show="auditOpen" preset="card" title="仓库资料变更记录"
          :style="{ width: 'min(900px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }">
          <p>升级前的修改历史无法推断；这里保留升级后新增、修改和删除的前后快照。</p>
          <p v-if="auditError" role="alert">{{ auditError }}</p>
          <div v-for="change in auditRows" :key="change.id" class="catalog-audit-item">
            <strong>#{{ change.id }} · {{ change.action === 'create' ? '新增' : change.action === 'update' ? '修改' : '删除' }}
              · 仓库 #{{ change.warehouse_id }}</strong>
            <span>{{ change.before?.code || '无' }} · {{ change.before?.name || '无' }} →
              {{ change.after?.code || '无' }} · {{ change.after?.name || '无' }}
              · 版本 {{ change.before?.version || '无' }} → {{ change.after?.version || '无' }}</span>
            <small>{{ change.reason }} · {{ change.changed_by_name }} · {{ localTime(change.created_at) }}</small>
          </div>
          <p v-if="!auditRows.length && !auditLoading">暂无升级后的变更记录。</p>
          <AppButton v-if="auditHasMore" type="button" variant="secondary" :disabled="auditLoading"
            @click="loadAudit(true)">加载更早记录</AppButton>
        </AppModal>
      </template>
      <template #cell-code="{ row: item }">{{ item.code }}</template>
      <template #cell-name="{ row: item }">{{ item.name }}</template>
      <template #cell-actions="{ row: item }"
        ><div class="catalog-actions">
          <template v-if="can('warehouse.manage')">
            <AppButton
              :disabled="busy || connectionLost || detailLoading"
              @click.capture="captureDialogOrigin('WarehousesView:form', $event)" @click="edit(item)"
              variant="text"
              type="button"
              >编辑</AppButton
            >
            <NPopconfirm
              positive-text="确认"
              negative-text="取消"
              @positive-click="deleteWarehouse(item.id, item.version)"
            >
              <template #trigger
                ><AppButton
                  :disabled="busy || connectionLost || item.id === 1"
                  variant="text"
                  type="button"
                  >删除</AppButton
                ></template
              >
              确认删除“{{ item.name }}”？已被业务记录引用的资料不能删除。
            </NPopconfirm>
          </template>
        </div></template
      >
      <template #empty>{{ query ? '没有匹配的仓库。' : '暂无仓库，请先新增。' }}</template>
    </WorkspaceTable>
  </section>
</template>
