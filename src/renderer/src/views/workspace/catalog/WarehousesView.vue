<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal, NPopconfirm } from 'naive-ui'
import type { Warehouse } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import './catalog.css'

const store = usePiniaAppStore()
const { busy, connectionLost, warehouses } = storeToRefs(store)
const { can, saveWarehouse, deleteWarehouse } = store
const query = ref('')
const editingId = ref<number | undefined>()
const showForm = ref(false)
const form = reactive({ code: '', name: '' })
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
function edit(item?: Warehouse): void {
  editingId.value = item?.id
  Object.assign(form, item ? { code: item.code, name: item.name } : { code: '', name: '' })
  showForm.value = true
}
async function save(): Promise<void> {
  if (await saveWarehouse({ ...form }, editingId.value)) showForm.value = false
}
</script>

<template>
  <section class="stack catalog-page">
    <!-- 主标题和说明统一由工作台外壳展示。 -->
    <WorkspaceTable dataset="warehouses" :query="query"
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
          @click="edit()"
          variant="primary"
          type="button"
          >新增仓库</AppButton
        >
      </template>
      <template #filters>
        <label class="catalog-search"
          >搜索仓库<AppInput v-model="query" placeholder="输入名称或编码搜索"
        /></label>
        <span class="muted">共 {{ warehouses.length }} 条</span>
      </template>
      <template #beforeTable>
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
        </NModal>
      </template>
      <template #cell-code="{ row: item }">{{ item.code }}</template>
      <template #cell-name="{ row: item }">{{ item.name }}</template>
      <template #cell-actions="{ row: item }"
        ><div class="catalog-actions">
          <template v-if="can('warehouse.manage')">
            <AppButton
              :disabled="busy || connectionLost"
              @click="edit(item)"
              variant="text"
              type="button"
              >编辑</AppButton
            >
            <NPopconfirm
              positive-text="确认"
              negative-text="取消"
              @positive-click="deleteWarehouse(item.id)"
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
