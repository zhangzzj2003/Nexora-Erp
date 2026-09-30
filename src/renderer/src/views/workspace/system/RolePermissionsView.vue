<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { NModal } from 'naive-ui'
import PermissionTreePicker from '../../../components/workspace/PermissionTreePicker.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { useAppStore } from '../../../store/app-store'
import { buildPermissionTree } from '../../../utils/permission-tree'
import { filterRoleRows, type RoleKindFilter } from '../../../utils/role-table'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  busy,
  error,
  roles,
  permissions,
  rolePermissionDrafts,
  roleLabelDrafts,
  newRole,
  createRole,
  saveRole
} = useAppStore()

// 页面按服务端提供的模块、单据层级组织操作权限，角色草稿仍只保存叶子代码。
const permissionModules = computed(() => buildPermissionTree(permissions.value))
const roleColumns = [
  { key: 'label', title: '职务名称', width: '34%' },
  { key: 'kind', title: '类型', width: '20%' },
  { key: 'permissions', title: '已授权操作', width: '25%' },
  { key: 'actions', title: '操作', width: '21%' }
]
const search = ref('')
const kind = ref<RoleKindFilter>('all')
const visibleRoles = computed(() => filterRoleRows(roles.value, search.value, kind.value))
const createOpen = ref(false)
const editorOpen = ref(false)
const selectedRoleCode = ref<string | null>(null)
const selectedRole = computed(() => roles.value.find((role) => role.code === selectedRoleCode.value) ?? null)

function openRole(code: string): void {
  selectedRoleCode.value = code
  editorOpen.value = true
}

async function submitNewRole(): Promise<void> {
  await createRole()
  // 共享操作会捕获并展示错误；只有服务端保存成功才关闭编辑窗口。
  if (!error.value) createOpen.value = false
}

async function submitRole(): Promise<void> {
  if (!selectedRole.value || selectedRole.value.is_builtin) return
  await saveRole(selectedRole.value.code)
  if (!error.value) editorOpen.value = false
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable dataset="roles" :query="search"
      :show-title="false"
      :data="visibleRoles"
      title="职务与权限"
      :columns="roleColumns"
      empty-text="没有符合条件的职务"
    >
      <template #actions>
        <AppButton type="button" :disabled="busy" @click="createOpen = true" variant="primary"
          >新增职务</AppButton
        >
      </template>
      <template #filters>
        <label class="role-table-search"
          >搜索职务
          <AppInput v-model.trim="search" type="search" placeholder="输入职务名称" />
        </label>
        <label class="role-table-filter"
          >类型
          <WorkspaceSelect
            v-model="kind"
            :options="[
              { label: '全部', value: 'all' },
              { label: '自定义', value: 'custom' },
              { label: '内置', value: 'builtin' }
            ]"
          />
        </label>
        <span class="muted role-table-count">共 {{ visibleRoles.length }} 项</span>
      </template>
      <template #cell-label="{ row: role }"
        ><strong>{{ role.label }}</strong></template
      >
      <template #cell-kind="{ row: role }">{{
        role.is_builtin ? '内置 · 只读' : '自定义'
      }}</template>
      <template #cell-permissions="{ row: role }">{{ role.permissions.length }} 项操作</template>
      <template #cell-actions="{ row: role }"
        ><AppButton type="button" @click="openRole(role.code)" variant="secondary" size="small">
          {{ role.is_builtin ? '查看权限' : '配置权限' }}
        </AppButton></template
      >
    </WorkspaceTable>

    <NModal
      v-model:show="createOpen"
      preset="card"
      title="新增职务"
      :mask-closable="!busy"
      :style="{ width: 'min(760px, calc(100vw - 32px))' }"
    >
      <form class="role-dialog-form" @submit.prevent="submitNewRole">
        <label
          >职务名称<AppInput
            v-model.trim="newRole.label"
            required
            maxlength="40"
            placeholder="例如 库存主管"
        /></label>
        <fieldset class="permission-tree-fieldset role-dialog-tree">
          <legend>授权范围</legend>
          <PermissionTreePicker
            v-model="newRole.permissions"
            :modules="permissionModules"
            :disabled="busy"
          />
        </fieldset>
        <div class="role-dialog-actions">
          <AppButton type="button" :disabled="busy" @click="createOpen = false" variant="secondary"
            >取消</AppButton
          >
          <AppButton type="submit" :disabled="busy" variant="primary">创建职务</AppButton>
        </div>
      </form>
    </NModal>

    <NModal
      v-model:show="editorOpen"
      preset="card"
      :title="selectedRole?.label ?? '职务权限'"
      :mask-closable="!busy"
      :style="{ width: 'min(760px, calc(100vw - 32px))' }"
    >
      <form v-if="selectedRole" class="role-dialog-form" @submit.prevent="submitRole">
        <label v-if="!selectedRole.is_builtin"
          >职务名称
          <AppInput v-model.trim="roleLabelDrafts[selectedRole.code]" required maxlength="40" />
        </label>
        <p v-else class="muted">内置职务只读，不能修改授权范围。</p>
        <fieldset class="permission-tree-fieldset role-dialog-tree">
          <legend>授权范围</legend>
          <PermissionTreePicker
            v-if="selectedRole.is_builtin"
            :model-value="selectedRole.permissions"
            :modules="permissionModules"
            readonly
          />
          <PermissionTreePicker
            v-else
            v-model="rolePermissionDrafts[selectedRole.code]"
            :modules="permissionModules"
            :disabled="busy"
          />
        </fieldset>
        <div class="role-dialog-actions">
          <AppButton type="button" :disabled="busy" @click="editorOpen = false" variant="secondary"
            >关闭</AppButton
          >
          <AppButton
            v-if="!selectedRole.is_builtin"
            type="submit"
            :disabled="busy"
            variant="primary"
            >保存权限</AppButton
          >
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.role-table-search {
  width: min(100%, 280px);
}
.role-table-filter {
  width: 145px;
}
.role-table-count {
  margin-left: auto;
  white-space: nowrap;
}
.role-dialog-form {
  display: grid;
  gap: 18px;
}
.role-dialog-tree {
  max-height: min(52vh, 540px);
  overflow-y: auto;
}
.role-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
@media (max-width: 650px) {
  .role-table-search {
    width: 100%;
  }
  .role-table-count {
    margin-left: 0;
  }
}
</style>
