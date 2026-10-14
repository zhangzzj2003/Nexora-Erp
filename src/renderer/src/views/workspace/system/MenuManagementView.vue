<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { usePiniaAppStore } from '../../../store/app-store'
import { workspaceRouteGroups } from '../../../router/workspace-routes'
import { menuIconComponents } from '../../../utils/menu-icon-components'
import { menuIconOptions, resolveMenuIcon } from '../../../../../shared/menu-icons'
import type { MenuIconKey } from '../../../../../shared/menu-icons'

const store = usePiniaAppStore()
const { menuIcons, busy, error } = storeToRefs(store)
const { loadMenuIcons, saveMenuIcon, displayError } = store
const query = ref('')
const iconQuery = ref('')
const loading = ref(false)
const loaded = ref(false)
const loadError = ref('')
interface MenuEntry {
  key: string
  label: string
  icon: MenuIconKey
  isGroup: boolean
}
// 菜单树从实际路由生成，不另建一份可漂移的名称或授权表。
const groups = computed(() =>
  workspaceRouteGroups
    .map((group) => ({
      key: group.key,
      label: group.label,
      entries: [
        ...(group.key === 'home'
          ? []
          : [{ key: `group:${group.key}`, label: group.label, icon: group.icon, isGroup: true }]),
        ...group.routes.map((route) => ({
          key: `route:${route.key}`,
          label: route.label,
          icon: route.icon,
          isGroup: false
        }))
      ].filter(
        (entry) =>
          entry.label.includes(query.value.trim()) || group.label.includes(query.value.trim())
      )
    }))
    .filter((group) => group.entries.length)
)
const editing = ref<MenuEntry | null>(null)
const selected = ref<MenuIconKey | null>(null)
const version = ref(0)
const saveError = ref('')
const options = computed(() =>
  menuIconOptions.filter((option) => option.label.includes(iconQuery.value.trim()))
)
function currentIcon(entry: MenuEntry): MenuIconKey {
  return resolveMenuIcon(menuIcons.value, entry.key, entry.icon)
}
function openEditor(entry: MenuEntry): void {
  editing.value = entry
  selected.value = menuIcons.value.find((item) => item.key === entry.key)?.icon ?? null
  version.value = menuIcons.value.find((item) => item.key === entry.key)?.version ?? 0
  iconQuery.value = ''
  saveError.value = ''
}
async function reload(): Promise<void> {
  if (loading.value || busy.value) return
  loading.value = true
  loadError.value = ''
  loaded.value = false
  try {
    await loadMenuIcons()
    loaded.value = true
  } catch (cause) {
    loadError.value = displayError(cause)
  } finally {
    loading.value = false
  }
}
async function save(): Promise<void> {
  if (!editing.value) return
  saveError.value = ''
  if (await saveMenuIcon(editing.value.key, selected.value, version.value)) editing.value = null
  else saveError.value = error.value || '未能保存，请稍后重试。'
}
// 打开页面时重新读取版本；冲突后关闭编辑器并重新加载，保留其他人的修改。
onMounted(reload)
</script>

<template>
  <section class="stack menu-management">
    <div class="card menu-toolbar">
      <label
        >查找菜单<AppInput v-model="query" type="search" placeholder="输入菜单或分组名称"
      /></label>
      <AppButton type="button" :disabled="loading || busy" @click="reload" variant="secondary"
        >重新加载</AppButton
      >
    </div>
    <p v-if="loading" role="status">正在加载菜单配置…</p>
    <p v-else-if="loadError" role="alert">加载失败：{{ loadError }}。请重新加载后再编辑。</p>
    <template v-else-if="loaded">
      <div v-for="group in groups" :key="group.key" class="card menu-group">
        <h3>{{ group.label }}</h3>
        <div v-for="entry in group.entries" :key="entry.key" class="menu-row">
          <span class="menu-preview"
            ><component :is="menuIconComponents[currentIcon(entry)]" aria-hidden="true"
          /></span>
          <div class="menu-name">
            <strong>{{ entry.label }}</strong
            ><small
              >{{ entry.isGroup ? '导航分组' : '页面入口' }} ·
              {{
                menuIcons.find((item) => item.key === entry.key)?.icon ? '自定义图标' : '默认图标'
              }}</small
            >
          </div>
          <AppButton
            type="button"
            :disabled="busy"
            :aria-label="`更换${entry.label}${entry.isGroup ? '分组' : '页面'}图标`"
            @click.capture="captureDialogOrigin('MenuManagementView:editor', $event)" @click="openEditor(entry)"
            variant="secondary"
            size="small"
            >更换图标</AppButton
          >
        </div>
      </div>
      <p v-if="!groups.length" class="muted">没有匹配的菜单。</p>
    </template>
    <AppModal :busy="busy" origin-key="MenuManagementView:editor" @invalidated="editing = null"
      :show="!!editing"
      preset="card"
      :title="`${editing?.label ?? ''} · 选择图标`"
      class="menu-icon-dialog"
      style="width: min(560px, calc(100vw - 40px))"
      :mask-closable="!busy"
      :close-on-esc="!busy"
      :closable="!busy"
      @update:show="
        (show) => {
          if (!show && !busy) editing = null
        }
      "
    >
      <template v-if="editing">
        <div class="menu-selection">
          <span class="menu-preview"
            ><component
              :is="menuIconComponents[selected ?? editing.icon]"
              aria-hidden="true" /></span
          ><strong>{{ editing.label }}</strong
          ><span class="muted">{{ selected ? '自定义图标' : '默认图标' }}</span>
        </div>
        <label
          >搜索图标<AppInput v-model="iconQuery" type="search" placeholder="如：仓库、财务、团队"
        /></label>
        <div class="menu-icon-grid" role="group" aria-label="可选图标">
          <AppButton
            v-for="option in options"
            :key="option.key"
            type="button"
            :aria-pressed="selected === option.key"
            :disabled="busy"
            @click="selected = option.key"
            class="menu-icon-option"
            variant="secondary"
          >
            <component :is="menuIconComponents[option.key]" aria-hidden="true" />{{ option.label }}
          </AppButton>
        </div>
        <p v-if="!options.length" class="muted">没有匹配的图标。</p>
        <p v-if="saveError" role="alert">{{ saveError }}</p>
        <div class="menu-dialog-actions">
          <AppButton
            type="button"
            :disabled="busy"
            @click="selected = null"
            variant="secondary"
            size="small"
            >恢复默认</AppButton
          >
          <span class="menu-action-spacer" />
          <AppButton
            type="button"
            :disabled="busy"
            @click="editing = null"
            variant="secondary"
            size="small"
            >取消</AppButton
          >
          <AppButton type="button" :disabled="busy" @click="save" variant="primary" size="small">{{
            busy ? '保存中…' : '保存图标'
          }}</AppButton>
        </div>
      </template>
    </AppModal>
  </section>
</template>

<style scoped>
/* 使用页面已有卡片与按钮主题，图标继承文字颜色，同时适配明暗模式。 */
.menu-toolbar,
.menu-row,
.menu-selection,
.menu-dialog-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.menu-toolbar {
  justify-content: space-between;
  flex-wrap: wrap;
}
.menu-toolbar label {
  width: min(100%, 340px);
}
.menu-group h3 {
  margin: 0 0 12px;
}
.menu-row {
  padding: 12px 0;
  border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}
.menu-preview {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: none;
  border-radius: 10px;
  background: color-mix(in srgb, #29b4aa 12%, transparent);
  color: #249e98;
}
.menu-preview svg,
.menu-icon-option svg {
  width: 22px;
  height: 22px;
  flex: none;
}
.menu-name {
  flex: 1;
  min-width: 0;
}
.menu-name small {
  display: block;
  margin-top: 5px;
  opacity: 0.65;
}
.menu-selection {
  margin-bottom: 20px;
}
.menu-icon-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin: 16px 0 22px;
  max-height: 40vh;
  overflow: auto;
  padding: 4px;
}
.menu-icon-option {
  height: auto;
  min-height: 70px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 4px;
  font-size: 12px;
}
.menu-icon-option[aria-pressed='true'] {
  outline: 2px solid #29b4aa;
  background: color-mix(in srgb, #29b4aa 18%, transparent);
}
.menu-action-spacer {
  flex: 1;
}
@media (max-width: 480px) {
  .menu-icon-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .menu-dialog-actions {
    gap: 8px;
    flex-wrap: wrap;
  }
}
/* 图标按钮的内容容器纵向排列，避免 Naive UI 内层把图标与文字挤在同一行。 */
.menu-icon-option :deep(.n-button__content) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  white-space: normal;
}
</style>
