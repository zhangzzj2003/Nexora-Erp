<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NDropdown } from 'naive-ui'
import IconRefreshLine from '~icons/ri/refresh-line'
import IconHome4Line from '~icons/ri/home-4-line'
import IconArrowRightSLine from '~icons/ri/arrow-right-s-line'
import AppButton from '../app/AppButton.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { routeGroupByKey, routeByKey } from '../../router/workspace-routes'

// 页面路径、菜单图标和权限全部读取共享 store，标题栏不另建导航状态。
const store = usePiniaAppStore()
const { activeTab, activeRouteAllowed, visibleGroups, busy, connectionLost, refreshingWorkspace } = storeToRefs(store)
const { navigateToRoute, refreshWorkspacePage } = store
const directoryOpen = ref(false)
const route = computed(() => routeByKey(activeTab.value))
const group = computed(() => visibleGroups.value.find((item) => item.key === routeGroupByKey(activeTab.value).key))
const directoryOptions = computed(() => (group.value?.routes ?? []).map((item) => ({
  key: item.key, label: item.label,
  icon: () => h(item.icon, { style: 'width: 16px; height: 16px' })
})))
function selectDirectory(key: string | number): void {
  // 下拉只允许进入当前账号可见的页面，不信任任意传入的菜单键。
  const selected = group.value?.routes.find((item) => item.key === key)
  if (selected) navigateToRoute(selected.key)
}
</script>

<template>
  <div class="workspace-title-navigation">
    <div class="workspace-title-tools">
      <AppButton type="button" variant="secondary" size="small" quaternary circle
        aria-label="刷新当前页面" title="刷新当前页面" :loading="refreshingWorkspace"
        :disabled="busy || connectionLost || !activeRouteAllowed" @click="refreshWorkspacePage">
        <template #icon><IconRefreshLine aria-hidden="true" /></template>
      </AppButton>
      <AppButton type="button" variant="secondary" size="small" quaternary circle
        aria-label="返回工作台首页" title="返回工作台首页" @click="navigateToRoute('home')">
        <template #icon><IconHome4Line aria-hidden="true" /></template>
      </AppButton>
    </div>
    <nav v-if="activeRouteAllowed" class="workspace-title-directory" aria-label="当前页面目录">
      <template v-if="group && group.key !== 'home'">
        <NDropdown v-model:show="directoryOpen" trigger="click" :options="directoryOptions" @select="selectDirectory">
          <AppButton type="button" variant="plain" class="workspace-directory-group"
            aria-haspopup="menu" :aria-expanded="directoryOpen" :aria-label="`${group.label}目录`" :title="group.label">
            <component :is="group.icon" class="workspace-directory-icon" aria-hidden="true" />
            <span class="workspace-directory-group-label">{{ group.label }}</span>
          </AppButton>
        </NDropdown>
        <IconArrowRightSLine class="workspace-directory-separator" aria-hidden="true" />
      </template>
      <span class="workspace-directory-page" aria-current="page" :title="route.label">{{ route.label }}</span>
    </nav>
  </div>
</template>

<style scoped>
/* 只将真实交互区排除出拖动范围，右侧空白仍可移动窗口。 */
.workspace-title-navigation { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.workspace-title-tools { display: flex; align-items: center; gap: 2px; flex: none; -webkit-app-region: no-drag; }
.workspace-title-directory { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 12px; color: var(--workspace-field-text); -webkit-app-region: no-drag; }
.workspace-directory-group { display: flex; align-items: center; gap: 6px; min-width: 0; max-width: 180px; padding: 5px; color: var(--workspace-field-accent); font-size: 12px; border-radius: 5px; }
.workspace-directory-group:hover { background: var(--app-button-secondary-hover); }
.workspace-directory-icon, .workspace-directory-separator { width: 16px; height: 16px; flex: none; }
.workspace-directory-separator { color: var(--workspace-field-muted); }
.workspace-directory-group-label, .workspace-directory-page { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-directory-page { min-width: 0; }
/* 窄窗口优先保留主页、刷新和当前页面；分类仍可通过图标打开目录。 */
@media (max-width: 620px) {
  .workspace-title-navigation { gap: 4px; }
  .workspace-title-directory { gap: 3px; }
  .workspace-directory-group-label { display: none; }
}
</style>
