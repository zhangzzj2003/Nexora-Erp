import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { test } from 'node:test'
import { parse } from '@vue/compiler-sfc'

// 覆盖详情入口清单，防止新业务或后续维护又在名称列直接铺开整份参数。
const root = 'src/renderer/src'
const details = [
  'components/workspace/DocumentApprovalDialog.vue',
  'components/workspace/DocumentApprovalPanel.vue',
  'components/workspace/InventoryDetailDialogs.vue',
  'components/workspace/ProductionAssociationDialog.vue',
  'components/workspace/WorkOrderMaterialFlowPanel.vue',
  'views/workspace/warehouse/OtherInboundsView.vue',
  'views/workspace/warehouse/ProductionMaterialFlowView.vue',
  'views/workspace/catalog/BomDetailDialog.vue',
  'views/workspace/catalog/ProductBomStructure.vue',
  'views/workspace/sales/CrmEvidence.vue',
  'views/workspace/sales/AfterSalesEvidence.vue',
  'views/workspace/production/QualityEvidence.vue',
  'views/workspace/production/EquipmentEvidence.vue',
  'views/workspace/production/MrpEvidence.vue'
]
const template = file => parse(readFileSync(join(root, file), 'utf8')).descriptor.template?.content ?? ''
function vueFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory()
    ? vueFiles(join(directory, entry.name)) : entry.name.endsWith('.vue') ? [join(directory, entry.name)] : [])
}

test('十四个详情名称入口统一使用名称组件，新增参数直铺入口会被发现', () => {
  for (const file of details) {
    assert.match(template(file), /<WorkspaceMaterialName\b/, file)
    assert.doesNotMatch(template(file), /<WorkspaceMaterialParameters\b/, file)
  }
  // 完整参数只允许留在独立物料详情及产品参数区，不能重新落入单据名称列。
  // 将系统路径分隔符统一为清单格式，避免 Windows 反斜杠导致相同文件被误判。
  const fullParameterViews = vueFiles(root).filter(file => /<WorkspaceMaterialParameters\b/.test(readFileSync(file, 'utf8')))
    .map(file => relative(root, file).split(sep).join('/')).sort()
  assert.deepEqual(fullParameterViews, ['components/workspace/InventoryMaterialFacts.vue', 'views/workspace/catalog/ProductsView.vue'])
})

test('名称、选择器和兼容参数组件共用一份资料卡，不再分别维护摘要与展开模板', () => {
  for (const file of ['WorkspaceMaterialName', 'WorkspaceMaterialSelect', 'WorkspaceMaterialParameters']) {
    const content = template(`components/workspace/${file}.vue`)
    assert.match(content, /<WorkspaceMaterialInfo\b/, file)
    assert.doesNotMatch(content, /class="workspace-material-(?:facts|summary|technical)"/, file)
  }
})
