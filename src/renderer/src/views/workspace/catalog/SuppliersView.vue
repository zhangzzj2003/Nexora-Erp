<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm } from 'naive-ui'
import type { Supplier, SupplierChange } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import { usePagedQuery } from '../../../composables/use-paged-query'
import { displayError } from '../../../utils/formatters'
import { supplierDraft, supplierStatusLabel } from '../../../../../shared/supplier-api'
import './catalog.css'

const store = usePiniaAppStore()
const { busy, error, notice, connectionLost, suppliers, materials, supplierMaterials } =
  storeToRefs(store)
const { can, saveSupplier, deleteSupplier, localTime } = store
const query = ref('')
const editingId = ref<number | undefined>()
const showForm = ref(false)
const form = reactive(supplierDraft())
const detailLoading = ref(false)
const detailError = ref('')
const auditOpen = ref(false)
const auditLoading = ref(false)
const auditError = ref('')
const auditRows = ref<SupplierChange[]>([])
const auditHasMore = ref(false)
// 列表从服务端分页获取；全量供应商快照仅供其他业务选项和供货关系使用。
const {
  rows,
  total,
  page,
  pageSize,
  loading,
  error: queryError,
  load,
  search
} = usePagedQuery<Supplier>(async (params) => {
  if (!window.nexora) throw new Error('服务连接不可用，请重新连接后重试。')
  return window.nexora.callApi('querySuppliers', params)
})
watch(query, search)
// 写入后的统一快照刷新、断线恢复都会重新查询当前页。
watch(
  [suppliers, connectionLost],
  () => {
    void load()
  },
  { immediate: true }
)
// 主列表与供货物料明细共用表格外壳，绑定关系的操作仍留在本页。
const supplierColumns = [
  { key: 'name', title: '供应商名称' },
  { key: 'status', title: '资料状态', width: '160px' },
  { key: 'contact_name', title: '联系人' },
  { key: 'phone', title: '联系电话' },
  { key: 'actions', title: '操作' }
]
const materialColumns = [
  { key: 'sku', title: '编码' },
  { key: 'name', title: '名称' },
  { key: 'unit', title: '单位' },
  { key: 'actions', title: '操作' }
]
async function edit(item?: Supplier): Promise<void> {
  detailError.value = ''
  if (!item) {
    editingId.value = undefined
    Object.assign(form, supplierDraft())
    showForm.value = true
    return
  }
  if (!window.nexora || connectionLost.value) return
  const user = store.user
  const server = store.server
  detailLoading.value = true
  try {
    const latest = await window.nexora.callApi('supplierDetail', { id: item.id })
    if (store.user !== user || store.server !== server || connectionLost.value) return
    editingId.value = item.id
    Object.assign(form, supplierDraft(latest))
    showForm.value = true
  } catch (cause) {
    detailError.value = displayError(cause)
  } finally {
    detailLoading.value = false
  }
}
async function save(): Promise<void> {
  if (await saveSupplier({ ...form }, editingId.value)) showForm.value = false
}
async function loadAudit(more = false): Promise<void> {
  if (!window.nexora || auditLoading.value || connectionLost.value) return
  const user = store.user
  const server = store.server
  auditError.value = ''
  auditLoading.value = true
  try {
    const rows = await window.nexora.callApi('recentSupplierChanges',
      more && auditRows.value.length ? { before_id: auditRows.value[auditRows.value.length - 1].id } : {})
    if (store.user !== user || store.server !== server || connectionLost.value) return
    auditRows.value = more ? [...auditRows.value, ...rows] : rows
    auditHasMore.value = rows.length === 100
  } catch (cause) {
    auditError.value = displayError(cause)
  } finally {
    auditLoading.value = false
  }
}
function openAudit(): void {
  auditRows.value = []
  auditOpen.value = true
  void loadAudit()
}
// 审计展示实际变化的联系资料，避免补全信息时只有名称和版本可见。
function changedSupplierFields(change: SupplierChange) {
  const labels = { contact_name: '联系人', phone: '联系电话', email: '电子邮箱', address: '地址',
    tax_number: '税号', bank_name: '开户银行', bank_account: '银行账号', notes: '备注' } as const
  return Object.entries(labels).map(([key, label]) => {
    const field = key as keyof typeof labels
    return { key, label, before: change.before?.[field] ?? '', after: change.after?.[field] ?? '' }
  }).filter(field => field.before !== field.after)
}
const selectedId = ref(0)
const bindOpen = ref(false)
const materialQuery = ref('')
const boundQuery = ref('')
const materialId = ref(0)
const selectedSupplier = computed(() =>
  suppliers.value.find((item) => item.id === selectedId.value)
)
const boundIds = computed(
  () =>
    new Set(
      supplierMaterials.value
        .filter((link) => link.supplier_id === selectedId.value)
        .map((link) => link.material_id)
    )
)
const boundMaterials = computed(() =>
  materials.value.filter(
    (item) =>
      boundIds.value.has(item.id) &&
      `${item.sku} ${item.name}`.toLowerCase().includes(boundQuery.value.trim().toLowerCase())
  )
)
const availableMaterials = computed(() =>
  materials.value.filter(
    (item) =>
      !boundIds.value.has(item.id) &&
      `${item.sku} ${item.name}`.toLowerCase().includes(materialQuery.value.trim().toLowerCase())
  )
)
watch(selectedId, () => {
  bindOpen.value = false
  materialId.value = 0
  materialQuery.value = ''
  boundQuery.value = ''
})
async function bindMaterial(): Promise<void> {
  if (!materialId.value || !selectedSupplier.value) return
  await store.setSupplierMaterial(selectedId.value, materialId.value, true)
  if (boundIds.value.has(materialId.value)) materialId.value = 0
}
async function submitBinding(): Promise<void> {
  await submitCreateDialog(bindMaterial, { busy, error, notice }, bindOpen)
}
</script>

<template>
  <section class="stack catalog-page">
    <!-- 主标题和说明统一由工作台外壳展示。 -->
    <WorkspaceTable
      :show-title="false"
      :data="rows"
      :loading="loading"
      :error="queryError"
      :pagination="{ page, pageSize, total, disabled: connectionLost }"
      @page-change="load"
      title="供应商列表"
      :columns="supplierColumns"
      :min-table-width="880"
    >
      <template #actions>
        <AppButton
          v-if="can('catalog.manage')"
          :disabled="busy || connectionLost"
          @click="edit()"
          variant="primary"
          type="button"
          >新增供应商</AppButton
        >
        <AppButton type="button" variant="secondary" :disabled="connectionLost || auditLoading"
          @click="openAudit">变更记录</AppButton>
      </template>
      <template #filters>
        <label class="catalog-search"
          >搜索供应商<AppInput v-model="query" placeholder="输入名称搜索" maxlength="120"
        /></label>
      </template>
      <template #errorActions
        ><AppButton
          type="button"
          :disabled="loading || connectionLost"
          @click="load()"
          variant="secondary"
          >重新查询</AppButton
        ></template
      >
      <template #beforeTable>
        <p v-if="detailError" role="alert">{{ detailError }}</p>
        <NModal
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
            v-if="showForm && can('catalog.manage')"
            class="catalog-editor"
            @submit.prevent="save"
          >
            <h3>{{ editingId ? '编辑供应商' : '新增供应商' }}</h3>
            <p class="material-hint">联系人、联系电话和地址填写完整后，状态自动变为“已完善”。资料可分次保存，未补齐时保留“待完善供应商”。</p>
            <fieldset class="material-section" :disabled="busy || connectionLost">
              <legend>供应商资料</legend>
              <div class="form-grid">
                <label>供应商名称 *<AppInput v-model.trim="form.name" required maxlength="120" /></label>
                <label>联系人<AppInput v-model.trim="form.contact_name" maxlength="80" /></label>
                <label>联系电话<AppInput v-model.trim="form.phone" maxlength="40" /></label>
                <label>电子邮箱<AppInput v-model.trim="form.email" inputmode="email" maxlength="150" /></label>
                <label class="supplier-wide">地址<AppInput v-model.trim="form.address" maxlength="300" /></label>
                <label>税号<AppInput v-model.trim="form.tax_number" maxlength="80" /></label>
                <label>开户银行<AppInput v-model.trim="form.bank_name" maxlength="120" /></label>
                <label class="supplier-wide">银行账号<AppInput v-model.trim="form.bank_account" maxlength="80" /></label>
                <label class="supplier-wide">备注<AppInput v-model.trim="form.notes" maxlength="1000" /></label>
                <label v-if="editingId" class="supplier-wide">修改原因 *<AppInput v-model.trim="form.reason" required maxlength="500" /></label>
              </div>
            </fieldset>
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
        </NModal>
        <NModal v-model:show="auditOpen" preset="card" title="供应商资料变更记录"
          :style="{ width: 'min(900px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }">
          <p>升级前的修改历史无法推断；这里保留升级后新增、修改和删除的前后快照。</p>
          <p v-if="auditError" role="alert">{{ auditError }}</p>
          <div v-for="change in auditRows" :key="change.id" class="catalog-audit-item">
            <strong>#{{ change.id }} · {{ change.action === 'create' ? '新增' : change.action === 'update' ? '修改' : '删除' }}
              · 供应商 #{{ change.supplier_id }}</strong>
            <span>{{ change.before?.name || '无' }} → {{ change.after?.name || '无' }}
              · 版本 {{ change.before?.version || '无' }} → {{ change.after?.version || '无' }}</span>
            <span v-for="field in changedSupplierFields(change)" :key="field.key">{{ field.label }}：{{ field.before || '未填写' }} → {{ field.after || '未填写' }}</span>
            <small>{{ change.reason }} · {{ change.changed_by_name }} · {{ localTime(change.created_at) }}</small>
          </div>
          <p v-if="!auditRows.length && !auditLoading">暂无升级后的变更记录。</p>
          <AppButton v-if="auditHasMore" type="button" variant="secondary" :disabled="auditLoading"
            @click="loadAudit(true)">加载更早记录</AppButton>
        </NModal>
      </template>
      <template #cell-status="{ row: item }"><span :class="item.profile_status === 'complete' ? 'supplier-complete' : 'supplier-pending'">{{ supplierStatusLabel(item) }}</span></template>
      <template #cell-contact_name="{ row: item }">{{ item.contact_name || '—' }}</template>
      <template #cell-phone="{ row: item }">{{ item.phone || '—' }}</template>
      <template #cell-name="{ row: item }">{{ item.name }}</template>
      <template #cell-actions="{ row: item }"
        ><div class="catalog-actions">
          <AppButton type="button" @click="selectedId = item.id" variant="text">供货物料</AppButton>
          <template v-if="can('catalog.manage')">
            <AppButton
              :disabled="busy || connectionLost || detailLoading"
              @click="edit(item)"
              variant="text"
              type="button"
              >{{ item.profile_status === 'complete' ? '编辑' : '完善资料' }}</AppButton
            >
            <NPopconfirm
              positive-text="确认"
              negative-text="取消"
              @positive-click="deleteSupplier(item.id, item.version)"
            >
              <template #trigger
                ><AppButton :disabled="busy || connectionLost" variant="text" type="button"
                  >删除</AppButton
                ></template
              >
              确认删除“{{ item.name }}”？关联的供货关系将一并移除。已被业务记录引用的资料不能删除。
            </NPopconfirm>
          </template>
        </div></template
      >
      <template #empty>{{ query ? '没有匹配的供应商。' : '暂无供应商，请先新增。' }}</template>
    </WorkspaceTable>
    <WorkspaceTable
      :data="boundMaterials"
      v-if="selectedSupplier"
      :title="`${selectedSupplier.name} · 供货物料`"
      description="绑定现有物料；同一物料可以同时绑定多家供应商。解绑只移除供货关系。"
      :columns="materialColumns"
      :min-table-width="580"
    >
      <template #actions>
        <AppButton
          v-if="can('catalog.manage')"
          type="button"
          :disabled="busy || connectionLost"
          @click="bindOpen = true"
          variant="primary"
          >绑定物料</AppButton
        >
        <AppButton type="button" @click="selectedId = 0" variant="text">关闭</AppButton>
      </template>
      <!-- 辅助列表也使用同一工具栏，说明和弹窗不占用筛选条件区域。 -->
      <template #filters>
        <label class="catalog-search"
          >搜索已绑定物料<AppInput v-model="boundQuery" placeholder="物料编码、名称或规格"
        /></label>
      </template>
      <template #beforeTable>
        <NModal
          v-model:show="bindOpen"
          preset="card"
          title="绑定物料"
          :mask-closable="!busy"
          :style="{ width: 'min(760px, calc(100vw - 32px))' }"
        >
          <form v-if="can('catalog.manage')" class="inline-form" @submit.prevent="submitBinding">
            <label
              >搜索可绑定物料<AppInput v-model="materialQuery" placeholder="物料编码、名称或规格"
            /></label>
            <label
              >选择物料<WorkspaceSelect
                v-model="materialId"
                required
                :options="[
                  { label: '请选择物料', value: 0, disabled: true },
                  ...availableMaterials.map((item) => ({
                    label: (item.sku + ' · ' + item.name + ' · ' + item.unit).trim(),
                    value: item.id
                  }))
                ]"
            /></label>
            <AppButton
              :disabled="busy || connectionLost || !materialId"
              variant="primary"
              type="submit"
              >绑定物料</AppButton
            >
            <span v-if="!availableMaterials.length" class="muted"
              >没有匹配的未绑定物料，可先到物料管理添加。</span
            >
          </form>
        </NModal>
      </template>
      <template #cell-sku="{ row: item }">{{ item.sku }}</template>
      <template #cell-name="{ row: item }">{{ item.name }}</template>
      <template #cell-unit="{ row: item }">{{ item.unit }}</template>
      <template #cell-actions="{ row: item }"
        ><NPopconfirm
          v-if="can('catalog.manage')"
          positive-text="确认"
          negative-text="取消"
          @positive-click="store.setSupplierMaterial(selectedId, item.id, false)"
        >
          <template #trigger
            ><AppButton :disabled="busy || connectionLost" variant="text" type="button"
              >解绑</AppButton
            ></template
          >解除此物料与供应商的供货关系？
        </NPopconfirm></template
      >
      <template #empty>{{ boundQuery ? '没有匹配的已绑定物料。' : '尚未绑定物料。' }}</template>
    </WorkspaceTable>
  </section>
</template>
