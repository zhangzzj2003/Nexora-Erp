<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, reactive, ref, watch } from 'vue'
import { NModal, NSwitch, NCheckbox } from 'naive-ui'
import type { User } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import { matchesRecordQuery } from '../../../utils/workspace-records'

const {
  error,
  notice,
  busy,
  user,
  roles,
  users,
  resetPasswords,
  newUser,
  createUser,
  updateUser,
  setUserStatus,
  resetUserPassword
} = useAppStore()
const editorOpen = ref(false)
const editingId = ref<number | null>(null)
const editDraft = reactive({ full_name: '', employee_no: '', phone: '', roles: [] as string[] })
const profile = computed(() => (editingId.value === null ? newUser.value : editDraft))
const editingUsername = ref('')
// 每次打开编辑复制最新已保存资料，取消不会改变列表中真实的角色和资料。
function openEditor(entry?: User): void {
  editingId.value = entry?.id ?? null
  editingUsername.value = entry?.username ?? ''
  if (entry)
    Object.assign(editDraft, {
      full_name: entry.full_name ?? '',
      employee_no: entry.employee_no ?? '',
      phone: entry.phone ?? '',
      roles: [...entry.roles]
    })
  editorOpen.value = true
}
async function submitEditor(): Promise<void> {
  await submitCreateDialog(
    () => (editingId.value === null ? createUser() : updateUser(editingId.value, editDraft)),
    { busy, error, notice },
    editorOpen
  )
}
const passwordOpen = ref(false)
const passwordTarget = ref<User | null>(null)
function openPassword(entry: User): void {
  resetPasswords.value[entry.id] = ''
  passwordTarget.value = entry
  passwordOpen.value = true
}
// 密码弹窗关闭即清除敏感草稿，避免取消后的密码留在跨页状态里。
watch(passwordOpen, (open) => {
  if (!open && passwordTarget.value) resetPasswords.value[passwordTarget.value.id] = ''
})
async function submitPassword(): Promise<void> {
  if (!passwordTarget.value) return
  await submitCreateDialog(
    () => resetUserPassword(passwordTarget.value!.id),
    { busy, error, notice },
    passwordOpen
  )
}
const userQuery = ref('')
const userColumns = [
  { key: 'id', title: 'ID', width: '80' },
  { key: 'account', title: '账号', width: '150' },
  { key: 'name', title: '姓名', width: '120' },
  { key: 'employee', title: '工号', width: '140' },
  { key: 'phone', title: '手机号', width: '170' },
  { key: 'roles', title: '角色', width: '190' },
  { key: 'actions', title: '操作', width: '350' }
]
const roleLabel = (code: string): string =>
  roles.value.find((role) => role.code === code)?.label ?? code
// 搜索仅包含可展示的资料和角色，绝不读取密码草稿。
const filteredUsers = computed(() =>
  users.value.filter((entry) =>
    matchesRecordQuery(userQuery.value, [
      entry.id,
      entry.username,
      entry.full_name,
      entry.employee_no,
      entry.phone,
      ...entry.roles.map(roleLabel)
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-model:show="editorOpen"
      preset="card"
      :title="editingId === null ? '创建用户' : `编辑用户 · ${editingUsername}`"
      :mask-closable="!busy"
      :closable="!busy"
      :close-on-esc="!busy"
      class="user-editor-modal"
      :style="{
        width: 'min(760px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <form class="stack" @submit.prevent="submitEditor">
        <div class="user-profile-grid">
          <template v-if="editingId === null">
            <label
              >账号<AppInput
                v-model.trim="newUser.username"
                required
                minlength="3"
                maxlength="40"
                pattern="[A-Za-z0-9_]+"
                placeholder="英文、数字或下划线"
                :disabled="busy"
            /></label>
            <label
              >初始密码<AppInput
                v-model="newUser.password"
                type="password"
                required
                minlength="12"
                maxlength="128"
                autocomplete="new-password"
                placeholder="至少 12 位"
                :disabled="busy"
            /></label>
          </template>
          <label
            >姓名<AppInput
              v-model.trim="profile.full_name"
              maxlength="60"
              placeholder="请输入姓名"
              :disabled="busy"
          /></label>
          <label
            >工号<AppInput
              v-model.trim="profile.employee_no"
              maxlength="40"
              pattern="[A-Za-z0-9_\-]+"
              placeholder="英文、数字、下划线或短横线"
              :disabled="busy"
          /></label>
          <label
            >手机号<AppInput
              v-model.trim="profile.phone"
              type="tel"
              maxlength="24"
              placeholder="手机号或带区号的联系电话"
              :disabled="busy"
          /></label>
        </div>
        <fieldset :disabled="busy">
          <legend>分配角色</legend>
          <!-- 角色名单也分页读取，勾选保存在草稿中，翻页不会丢失已选角色。 -->
          <WorkspaceTable dataset="roles" title="可分配角色" :columns="[{ key: 'label', title: '角色' }, { key: 'choice', title: '选择' }]" :data="roles">
            <template #cell-choice="{ row: role }">
              <NCheckbox :disabled="busy" :checked="profile.roles.includes(role.code)" @update:checked="checked => { profile.roles = checked ? [...profile.roles, role.code] : profile.roles.filter(code => code !== role.code) }">{{ role.label }}</NCheckbox>
            </template>
          </WorkspaceTable>
        </fieldset>
        <p class="muted">用户资料可稍后补齐；填写工号时须保持唯一，至少分配一个角色。</p>
        <div class="form-actions">
          <AppButton type="button" :disabled="busy" @click="editorOpen = false" variant="secondary"
            >取消</AppButton
          >
          <AppButton type="submit" :disabled="busy || !profile.roles.length" variant="primary">{{
            editingId === null ? '创建用户' : '保存修改'
          }}</AppButton>
        </div>
      </form>
    </NModal>
    <NModal
      v-model:show="passwordOpen"
      preset="card"
      title="重置密码"
      :mask-closable="!busy"
      :closable="!busy"
      :close-on-esc="!busy"
      :style="{ width: 'min(480px, calc(100vw - 32px))' }"
    >
      <form v-if="passwordTarget" class="stack" @submit.prevent="submitPassword">
        <p>为 {{ passwordTarget.username }} 设置新密码，保存后该账号需要重新登录。</p>
        <label
          >新密码<AppInput
            v-model="resetPasswords[passwordTarget.id]"
            type="password"
            required
            minlength="12"
            maxlength="128"
            autocomplete="new-password"
            placeholder="至少 12 位"
            :disabled="busy"
        /></label>
        <div class="form-actions">
          <AppButton
            type="button"
            :disabled="busy"
            @click="passwordOpen = false"
            variant="secondary"
            >取消</AppButton
          >
          <AppButton
            type="submit"
            :disabled="busy || (resetPasswords[passwordTarget.id]?.length ?? 0) < 12"
            variant="primary"
            >确认重置</AppButton
          >
        </div>
      </form>
    </NModal>
    <WorkspaceTable dataset="users" :query="userQuery"
      :show-title="false"
      title="用户管理"
      :columns="userColumns"
      :data="filteredUsers"
      :min-table-width="1200"
    >
      <template #actions
        ><AppButton type="button" :disabled="busy" @click="openEditor()" variant="primary"
          >创建用户</AppButton
        ></template
      >
      <template #filters
        ><label
          >搜索用户<AppInput
            v-model="userQuery"
            placeholder="搜索 ID、账号、姓名、工号、手机号或角色" /></label
      ></template>
      <template #cell-id="{ row: entry }">{{ entry.id }}</template>
      <template #cell-account="{ row: entry }"
        ><strong>{{ entry.username }}</strong></template
      >
      <template #cell-name="{ row: entry }">{{ entry.full_name || '—' }}</template>
      <template #cell-employee="{ row: entry }">{{ entry.employee_no || '—' }}</template>
      <template #cell-phone="{ row: entry }">{{ entry.phone || '—' }}</template>
      <template #cell-roles="{ row: entry }"
        ><div class="user-role-labels">
          <span v-for="code in entry.roles" :key="code" class="user-role-label">{{
            roleLabel(code)
          }}</span>
        </div></template
      >
      <template #cell-actions="{ row: entry }">
        <div class="form-actions">
          <AppButton
            type="button"
            :disabled="busy"
            @click="openEditor(entry)"
            variant="secondary"
            size="small"
            >编辑</AppButton
          >
          <AppButton
            type="button"
            :disabled="busy || entry.id === user?.id"
            @click="openPassword(entry)"
            variant="secondary"
            size="small"
            >重置密码</AppButton
          >
          <!-- 受控开关只展示服务端快照，失败时保持原状态；禁止停用当前登录账号。 -->
          <NSwitch
            :value="entry.is_active"
            :disabled="busy || entry.id === user?.id"
            :aria-label="`${entry.username}账号状态`"
            @update:value="setUserStatus(entry)"
          >
            <template #checked>启用账号</template><template #unchecked>停用账号</template>
          </NSwitch>
        </div>
      </template>
      <template #empty>{{ userQuery ? '没有匹配的用户。' : '暂无用户。' }}</template>
    </WorkspaceTable>
  </section>
</template>

<style scoped>
/* 资料字段分两列排列，小窗口下自然折行，不挤压操作和角色内容。 */
.user-profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.user-role-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.user-role-label {
  padding: 4px 9px;
  border-radius: 6px;
  background: rgba(44, 153, 150, 0.12);
}
@media (max-width: 600px) {
  .user-profile-grid {
    grid-template-columns: 1fr;
  }
}
</style>
