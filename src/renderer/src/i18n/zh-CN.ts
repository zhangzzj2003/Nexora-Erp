import type { Screen } from '../store/types'

// 引导标题保留统一阶段索引，英文显示通过公共文案表即时翻译。
export const onboardingCopy: Record<
  Screen,
  { title: string; description: string }
> = {
  numbering: { title: '设置单据编号规则', description: '由管理员选择实例的编号风格和业务时区。' },
  loading: { title: '正在准备工作台', description: '请稍候。' },
  welcome: {
    title: '选择你的工作方式',
    description: '连接团队已有的服务端，或者在这台电脑上创建一个。'
  },
  manual: {
    title: '连接现有服务端',
    description: '输入局域网地址，连接团队的 Nexora ERP。'
  },
  scan: {
    title: '正在查找局域网服务端',
    description: '正在发现同一局域网中可用的 Nexora 服务端。'
  },
  results: {
    title: '选择服务端',
    description: '以下服务端由当前网络实际发现；选择后仍需核对身份。'
  },
  create: {
    title: '创建本机服务端',
    description: '数据保存在所选目录；安装版由系统服务持续运行。'
  },
  trust: {
    title: '核对服务端身份',
    description: '请与服务端电脑上的指纹逐字核对，再使用账号密码登录。'
  },
  ready: {
    title: '服务端已就绪',
    description: '连接和服务状态已确认，可以进入工作台。'
  },
  offline: {
    title: '连接暂时中断',
    description: '检查网络或本机服务，再试一次。'
  },
  setup: { title: '正在准备工作台', description: '请稍候。' },
  login: { title: '正在准备工作台', description: '请稍候。' },
  app: { title: '正在准备工作台', description: '请稍候。' }
}
