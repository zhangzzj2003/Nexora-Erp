<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../components/app/AppButton.vue'
import { computed } from 'vue'
import { useAppStore } from '../store/app-store'
// 工作台专属导航与跨页面公共组件分目录，避免应用外壳继续依赖平铺组件路径。
import WorkspaceSidebar from '../components/workspace/WorkspaceSidebar.vue'
import ThemeToggle from '../components/app/ThemeToggle.vue'
import WorkspaceTabs from '../components/workspace/WorkspaceTabs.vue'
import AppStatusFooter from '../components/app/AppStatusFooter.vue'
import AuthView from './AuthView.vue'
import { nexoraLogo } from '../assets/brand'
import { accountRoleText } from '../utils/account-role'
import { workspacePageDescriptions } from '../utils/workspace-page-copy'

const {
  screen,
  activeTab,
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
const isAuthScreen = computed(() => screen.value === 'setup' || screen.value === 'login')
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
      <!-- 标签独占标题栏下方、侧栏右侧的一行，不随业务内容滚动。 -->
      <WorkspaceTabs v-if="screen === 'app'" class="workspace-page-tabs" />
      <div class="content-body" :class="{ 'auth-screen': isAuthScreen }">
        <header class="topbar">
          <!-- 登录标题沿用侧栏的品牌图形，保持未登录和工作台的视觉识别一致。 -->
          <span v-if="isAuthScreen" class="auth-header-mark" aria-hidden="true">
            <img :src="nexoraLogo" alt="" />
          </span>
          <div>
            <p class="eyebrow">NEXORA WORKSPACE</p>
            <h1>
              {{
                screen === 'app'
                  ? visibleTabs.find((item) => item.key === activeTab)?.label
                  : '开始使用联光 ERP'
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
          <div v-if="user" class="account">
            <!-- 侧栏在窄窗口收起时，顶部保留账号和退出操作。 -->
            <span class="account-identity"
              >{{ user.username }}<small>{{ accountRole }}</small></span
            ><ThemeToggle /><AppButton type="button" @click="logout" variant="text">
              退出登录
            </AppButton>
          </div>
        </header>

        <AuthView v-if="isAuthScreen" />
        <template v-else-if="screen === 'app' && activeRouteAllowed">
          <!-- 工作台页面由 Vue Router 装载；权限守卫和服务端鉴权共同约束访问。 -->
          <RouterView />
        </template>
      </div>
      <AppStatusFooter />
    </main>
  </div>
</template>

<style scoped>
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
