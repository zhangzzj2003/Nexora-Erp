import { readFileSync } from 'node:fs'
import postcss from 'postcss'

// 构建时仅抽取展示节点需要的规则，并逐个选择器加作用域，避免项目样式污染官网。
export function displayStyles() {
  const classes = /\.(?:sidebar(?:-bottom|-account-avatar)?|brand(?:-mark)?|side-group|nav-group|side-category|category-chevron|nav-panel|nav-list|nav-item|nav-home|nav-icon|content(?:-body)?|workspace-tabs|workspace-tab(?:-link|-close)?|topbar|eyebrow|card|muted|pill|workspace-table(?:-[\w-]+)?|workspace-vxe-table|workspace-record-lines|app-titlebar(?:-[\w-]+)?)(?![\w-])/
  const sources=['src/renderer/src/style.css','src/renderer/src/light-theme.css']
  const components=['src/renderer/src/components/workspace/WorkspaceTable.vue','src/renderer/src/components/app/AppTitleBar.vue']
  const css=[...sources.map(path=>readFileSync(new URL('../'+path,import.meta.url),'utf8')),...components.flatMap(path=>[...readFileSync(new URL('../'+path,import.meta.url),'utf8').matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map(match=>match[1]))]
  const output=postcss.root()
  for(const source of css) {
    const root=postcss.parse(source)
    // 响应式由官网镜头处理，不复制应用断点、深色主题、过渡或 Tailwind 全局指令。
    for(const node of root.nodes) if(node.type==='rule') {
      const selectors=node.selectors.filter(selector=>classes.test(selector)&&!selector.includes("data-theme='dark'")).map(selector=>{
        const clean=selector.replace(/:deep\(([^)]+)\)/g,'$1')
        return clean.includes(':root') ? clean.replace(/:root/g,'.erp-display') : '.erp-display '+clean
      })
      if(selectors.length) output.append(node.clone({selectors}))
    }
  }
  return '/* 构建时复用工作台、浅色主题和共享表格规则；只作用于官网展示。 */\n'+output.toString()+'\n'+readFileSync(new URL('../docs/site/erp-display.css',import.meta.url),'utf8')
}
