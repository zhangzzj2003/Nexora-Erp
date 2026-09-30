<script setup lang="ts" generic="T extends CustomerInput">
import { computed } from 'vue'
import { NSwitch } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import type { CustomerInput, User } from '../../../../../shared/erp-api'
// 新增与修改复用档案字段，表单草稿由父页面的 Pinia 状态持有。
const model = defineModel<T>({ required: true })
const props = defineProps<{ admin: boolean; users: User[]; disabled: boolean }>()
const ownerOptions = computed(() => [{ value: 0, label: '待分配' }, ...props.users.filter(user => user.is_active).map(user => ({ value: user.id, label: user.full_name || user.username }))])
const owner = computed({ get: () => model.value.owner_id ?? 0, set: (value: number) => { model.value.owner_id = value || null } })
const active = computed({ get: () => model.value.is_active !== false, set: (value: boolean) => { model.value.is_active = value } })
</script>
<template>
  <label>客户名称<AppInput v-model.trim="model.name" required maxlength="120" :disabled="disabled" /></label>
  <label>联系人<AppInput v-model.trim="model.contact_name" maxlength="60" :disabled="disabled" /></label>
  <label>联系电话<AppInput v-model.trim="model.phone" maxlength="40" :disabled="disabled" /></label>
  <label>地址<AppInput v-model.trim="model.address" maxlength="300" :disabled="disabled" /></label>
  <label>备注<AppInput v-model.trim="model.note" maxlength="500" :disabled="disabled" /></label>
  <label v-if="admin">负责商务<WorkspaceSelect v-model="owner" remote-dataset="users" :options="ownerOptions" :disabled="disabled" /></label>
  <label>客户启用<NSwitch v-model:value="active" :disabled="disabled" /></label>
</template>
