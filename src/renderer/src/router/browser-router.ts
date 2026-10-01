import { createWebHashHistory, createMemoryHistory } from 'vue-router'
import { createWorkspaceRouter } from './index'

// 桌面安装包可通过 file:// 加载，Hash 模式也保留现有的页面书签地址。
export const workspaceRouter = createWorkspaceRouter(typeof window === 'undefined' || typeof location === 'undefined' ? createMemoryHistory() : createWebHashHistory())
