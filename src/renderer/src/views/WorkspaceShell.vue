<script setup lang="ts">
// 公共界面文案随语言偏好即时更新，不影响输入草稿。
import { useSettingsStore } from '../store/settings-store'
const { t } = useSettingsStore()

// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../components/app/AppButton.vue'
import { computed } from 'vue'
import { useAppStore } from '../store/app-store'
// 工作台专属导航与跨页面公共组件分目录，避免应用外壳继续依赖平铺组件路径。
import WorkspaceSidebar from '../components/workspace/WorkspaceSidebar.vue'
import ThemeToggle from '../components/app/ThemeToggle.vue'
import AppSettingsButton from '../components/app/AppSettingsButton.vue'
import WorkspaceTabs from '../components/workspace/WorkspaceTabs.vue'
import WorkspaceTitleNavigation from '../components/workspace/WorkspaceTitleNavigation.vue'
import { usesIntegratedTitleBar } from '../../../shared/window-chrome'
import AppStatusFooter from '../components/app/AppStatusFooter.vue'
import AuthView from './AuthView.vue'
import DocumentNumberingSettings from '../components/workspace/DocumentNumberingSettings.vue'
import { nexoraLogo } from '../assets/brand'
import { accountRoleText } from '../utils/account-role'
import { workspacePageDescriptions } from '../utils/workspace-page-copy'

const {
  screen,
  documentNumbering: storeNumbering,
  activeTab,
  workspacePageVersion,
  expandedGroupKey,
  busy,
  user,
  username,
  password,
  roles,
  visibleGroups,
  visibleTabs,
  openedTabs,
  activeRouteAllowed,
  toggleRouteGroup,
  navigateToRoute,
  closeOpenedRoute,
  switchServer,
  authenticate,
  logout
} = useAppStore()

// 登录、初始化和工作台共用内容区域与底栏。
const isNumberingScreen = computed(() => screen.value === 'numbering')
const isAuthScreen = computed(() => screen.value === 'setup' || screen.value === 'login')
// 浏览器和 Linux 没有融合标题栏，仍在内容顶部提供统一导航与主题入口。
const integratedTitleBar = usesIntegratedTitleBar(window.nexora?.platform)
// 窄窗口与侧栏账号卡片共用角色名称规则，避免同一用户显示两种称呼。
const accountRole = computed(() => accountRoleText(user.value?.roles ?? [], roles.value))
</script>

<template>
  <div class="app-shell" :class="{ 'has-sidebar': screen === 'app' }">
    <!-- 只在进入工作台后挂载侧栏，进出时与内容列共用同一段过渡。 -->
    <Transition name="sidebar-slide">
      <WorkspaceSidebar v-if="screen === 'app'" />
    </Transition>

    <main class="content">
      <header v-if="screen === 'app' && !integratedTitleBar" class="workspace-browser-toolbar">
        <WorkspaceTitleNavigation /><ThemeToggle /><AppSettingsButton />
      </header>
      <!-- 标签独占标题栏下方、侧栏右侧的一行，不随业务内容滚动。 -->
      <WorkspaceTabs v-if="screen === 'app'" class="workspace-page-tabs" />
      <div class="content-body" :class="{ 'auth-screen': isAuthScreen, 'numbering-onboarding': isNumberingScreen }">
        <header v-if="!isNumberingScreen" class="topbar">
          <!-- 登录标题沿用侧栏的品牌图形，保持未登录和工作台的视觉识别一致。 -->
          <span v-if="isAuthScreen" class="auth-header-mark" aria-hidden="true">
            <img :src="nexoraLogo" alt="" />
          </span>
          <div class="workspace-page-title">
            <p class="eyebrow">NEXORA WORKSPACE</p>
            <h1>
              {{
                screen === 'app'
                  ? t(visibleTabs.find((item) => item.key === activeTab)?.label ?? '')
                  : t('开始使用联光 ERP')
              }}
            </h1>
            <!-- 页面说明放在主标题下方，与卡片中的操作和筛选分层。 -->
            <p
              v-if="screen === 'app' && activeRouteAllowed && workspacePageDescriptions[activeTab]"
              class="muted workspace-page-description"
            >
              {{ workspacePageDescriptions[activeTab] }}
            </p>
          </div>
          <!-- 页面把统计控件放到标题右侧，筛选状态仍归业务页面管理；卸载时自动移除。 -->
          <div v-if="screen === 'app' && activeRouteAllowed" id="workspace-page-summary" class="workspace-page-summary" />
          <div v-if="user" class="account">
            <!-- 侧栏在窄窗口收起时，顶部保留账号和退出操作。 -->
            <span class="account-identity"
              >{{ user.username }}<small>{{ accountRole }}</small></span
            ><AppButton type="button" :disabled="busy" @click="logout" variant="text">{{ t("退出登录") }}</AppButton>
          </div>
          <!-- 浏览器和 Linux 登录页没有融合顶部栏，仍保留右上角设置入口。 -->
          <div v-if="(isAuthScreen || screen === 'numbering') && !integratedTitleBar" class="auth-settings-actions"><ThemeToggle /><AppSettingsButton /></div>
        </header>

        <!-- 首次编号设置的标题随卡片居中，退出和全局设置留在独立的顶部操作区。 -->
        <header v-if="isNumberingScreen" class="numbering-session-bar">
          <span v-if="user" class="numbering-account">{{ user.username }} · {{ accountRole }}</span>
          <AppButton type="button" variant="text" :disabled="busy" @click="logout">{{ t('退出登录') }}</AppButton>
          <template v-if="!integratedTitleBar"><ThemeToggle /><AppSettingsButton /></template>
        </header>
        <AuthView v-if="isAuthScreen" />
        <DocumentNumberingSettings v-else-if="screen === 'numbering'" initial />
        <template v-else-if="screen === 'app' && activeRouteAllowed">
          <p v-if="storeNumbering && !storeNumbering.configured" role="status">{{ t('管理员尚未设置单据编号规则，当前业务只可查看。') }}</p>
          <!-- 工作台页面由 Vue Router 装载；权限守卫和服务端鉴权共同约束访问。 -->
          <RouterView :key="`${activeTab}-${workspacePageVersion}`" />
        </template>
      </div>
      <AppStatusFooter />
    </main>
  </div>
</template>

<style scoped>
/* 仅有统计内容时调整标题布局；其他页面与登录页保持原有头部行为。 */
.topbar:has(.workspace-page-summary:not(:empty)) { flex-wrap: wrap; }
.topbar:has(.workspace-page-summary:not(:empty)) .workspace-page-title { flex: 1 1 400px; min-width: 0; }
.workspace-page-summary { flex: 0 1 650px; min-width: 0; max-width: 100%; margin-left: auto; container-type: inline-size; }
.workspace-page-summary:empty { display: none; }

/* 桌面工作台缩小左右留白，让标题和业务卡片共用更宽的内容区；窄屏沿用原间距。 */
@media (min-width: 761px) {
  .has-sidebar .content-body { padding-inline: clamp(24px, 2vw, 32px); }
}

/* 自动外边距只在内容足够时居中；矮窗口从顶部滚动，固定底栏不被卡片挤走。 */
.content-body.numbering-onboarding { display: flex; flex-direction: column; padding: 20px clamp(16px, 4vw, 62px) 24px; }
.numbering-session-bar { display: flex; flex: none; align-items: center; justify-content: flex-end; gap: 8px; min-height: 32px; margin-bottom: 16px; }
.numbering-account { color: var(--workspace-field-muted); font-size: 12px; margin-right: 4px; }
.numbering-onboarding > .numbering-settings { flex: none; margin: auto; }
@media (max-width: 420px) { .numbering-account { max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.workspace-browser-toolbar { display: flex; align-items: center; gap: 12px; flex: none; height: 48px; padding: 0 12px; border-bottom: 1px solid var(--workspace-field-border); }
.auth-settings-actions { display: flex; align-items: center; margin-left: auto; }
/* 标签栏脱离内容区的内边距布局，首个标签贴近侧栏边缘。 */
.workspace-page-tabs {
  flex: none;
  margin: 0;
  padding: 7px clamp(25px, 4vw, 62px) 0 6px;
}
.workspace-page-description {
  max-width: 960px;
  margin: 12px 0 0;
  line-height: 1.7;
  font-size: 13px;
}
</style>
