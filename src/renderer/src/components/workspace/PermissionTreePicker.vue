<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../app/AppButton.vue'
import { computed, ref } from 'vue'
import { NCheckbox } from 'naive-ui'
import type { PermissionModule } from '../../utils/permission-tree'
import {
  documentPermissionCodes,
  documentPermissionGroups,
  modulePermissionCodes,
  operationGroupPermissionCodes,
  selectedPermissionCount,
  togglePermissionCodes
} from '../../utils/permission-tree'

const props = defineProps<{
  modules: PermissionModule[]
  modelValue: string[]
  disabled?: boolean
  readonly?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [codes: string[]] }>()
// Naive UI 直接回传勾选值，保留模块/单据的半选与只读保护。
// 展开状态只影响页面浏览；勾选状态由角色草稿持有，切换页面也不会丢失。
const expandedModules = ref<Record<string, boolean>>({})
const expandedDocuments = ref<Record<string, boolean>>({})
// 分类只负责展示和批量选择；角色草稿和保存接口仍使用原有权限代码。
const groupedModules = computed(() =>
  props.modules.map((module) => ({
    ...module,
    documents: module.documents.map((document) => ({
      ...document,
      operationGroups: documentPermissionGroups(document)
    }))
  }))
)

function toggleCodes(codes: string[], checked: boolean): void {
  if (props.disabled || props.readonly) return
  emit('update:modelValue', togglePermissionCodes(props.modelValue, codes, checked))
}

function documentKey(moduleCode: string, documentCode: string): string {
  return `${moduleCode}/${documentCode}`
}
</script>

<template>
  <div class="permission-tree">
    <div v-for="module in groupedModules" :key="module.code" class="permission-tree-module">
      <div class="permission-tree-heading">
        <NCheckbox
          :aria-label="`选择${module.label}全部操作`"
          :checked="
            selectedPermissionCount(modelValue, modulePermissionCodes(module)) ===
            modulePermissionCodes(module).length
          "
          :indeterminate="
            selectedPermissionCount(modelValue, modulePermissionCodes(module)) > 0 &&
            selectedPermissionCount(modelValue, modulePermissionCodes(module)) <
              modulePermissionCodes(module).length
          "
          :disabled="disabled || readonly"
          @update:checked="(checked) => toggleCodes(modulePermissionCodes(module), checked)"
        />
        <AppButton
          type="button"
          :aria-expanded="Boolean(expandedModules[module.code])"
          @click="expandedModules[module.code] = !expandedModules[module.code]"
          class="permission-tree-expand"
          variant="plain"
        >
          <span aria-hidden="true">{{ expandedModules[module.code] ? '▾' : '▸' }}</span>
          <strong>{{ module.label }}</strong>
          <small
            >{{ selectedPermissionCount(modelValue, modulePermissionCodes(module)) }}/{{
              modulePermissionCodes(module).length
            }}</small
          >
        </AppButton>
      </div>
      <div
        v-if="expandedModules[module.code]"
        class="permission-tree-children"
        role="group"
        :aria-label="module.label"
      >
        <div
          v-for="document in module.documents"
          :key="document.code"
          class="permission-tree-document"
        >
          <div class="permission-tree-heading">
            <NCheckbox
              :aria-label="`选择${document.label}全部操作`"
              :checked="
                selectedPermissionCount(modelValue, documentPermissionCodes(document)) ===
                document.permissions.length
              "
              :indeterminate="
                selectedPermissionCount(modelValue, documentPermissionCodes(document)) > 0 &&
                selectedPermissionCount(modelValue, documentPermissionCodes(document)) <
                  document.permissions.length
              "
              :disabled="disabled || readonly"
              @update:checked="(checked) => toggleCodes(documentPermissionCodes(document), checked)"
            />
            <AppButton
              type="button"
              :aria-expanded="Boolean(expandedDocuments[documentKey(module.code, document.code)])"
              @click="
                expandedDocuments[documentKey(module.code, document.code)] =
                  !expandedDocuments[documentKey(module.code, document.code)]
              "
              class="permission-tree-expand"
              variant="plain"
            >
              <span aria-hidden="true">{{
                expandedDocuments[documentKey(module.code, document.code)] ? '▾' : '▸'
              }}</span>
              <span>{{ document.label }}</span>
              <small
                >{{ selectedPermissionCount(modelValue, documentPermissionCodes(document)) }}/{{
                  document.permissions.length
                }}</small
              >
            </AppButton>
          </div>
          <div
            v-if="expandedDocuments[documentKey(module.code, document.code)]"
            class="permission-tree-categories"
            role="group"
            :aria-label="document.label"
          >
            <div
              v-for="group in document.operationGroups"
              :key="group.code"
              class="permission-tree-category"
              role="group"
              :aria-label="`${document.label}${group.label}`"
            >
              <div class="permission-tree-category-heading">
                <NCheckbox
                  :aria-label="`选择${document.label}全部${group.label}`"
                  :checked="
                    selectedPermissionCount(modelValue, operationGroupPermissionCodes(group)) ===
                    group.permissions.length
                  "
                  :indeterminate="
                    selectedPermissionCount(modelValue, operationGroupPermissionCodes(group)) > 0 &&
                    selectedPermissionCount(modelValue, operationGroupPermissionCodes(group)) <
                      group.permissions.length
                  "
                  :disabled="disabled || readonly"
                  @update:checked="(checked) => toggleCodes(operationGroupPermissionCodes(group), checked)"
                  >{{ group.label }}</NCheckbox
                >
                <small
                  >{{ selectedPermissionCount(modelValue, operationGroupPermissionCodes(group)) }}/{{
                    group.permissions.length
                  }}</small
                >
              </div>
              <div class="permission-tree-leaves">
                <NCheckbox
                  v-for="permission in group.permissions"
                  :key="permission.code"
                  class="check"
                  :checked="modelValue.includes(permission.code)"
                  :disabled="disabled || readonly"
                  @update:checked="(checked) => toggleCodes([permission.code], checked)"
                  >{{ permission.label }}</NCheckbox
                >
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 分类标题和分隔线使用现有主题变量，窄窗口自动改为单列且不截断权限名称。 */
.permission-tree-categories {
  display: grid;
  gap: 12px;
  padding: 4px 12px 14px 36px;
}
.permission-tree-category + .permission-tree-category {
  border-top: 1px solid var(--workspace-field-border);
  padding-top: 12px;
}
.permission-tree-category-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--workspace-field-accent);
  font-weight: 600;
}
.permission-tree-category-heading small {
  margin-left: auto;
  color: var(--workspace-field-muted);
  font-size: 11px;
  font-weight: 400;
}
.permission-tree-category .permission-tree-leaves {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  padding: 10px 0 0;
}
@media (max-width: 650px) {
  .permission-tree-categories {
    padding-left: 12px;
    padding-right: 4px;
  }
}
</style>
