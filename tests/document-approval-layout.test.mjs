import assert from 'node:assert/strict'
import { test } from 'node:test'
import { documentApprovalLayout } from '../src/renderer/src/utils/document-approval-layout.ts'

// 数量和名称必须取送审摘要，分区不得格式化、截断或修改服务端快照。
test('其他入库摘要分为基础信息与物料表，保留重复行、长说明及原始精度', () => {
  const summary = [{ label: '仓库', value: '主仓库' }, { label: '用途', value: '赠品' },
    { label: '入库说明', value: '长说明\n'.repeat(100) }, { label: '参考号', value: '—' },
    { label: 'EL-001 · 电阻', value: '0.125 个' }, { label: 'EL-001 · 电阻', value: '1000 个' }]
  const record = { document_type: 'WarehouseInbound', summary, content_matches: false }
  const before = structuredClone(record)
  const layout = documentApprovalLayout(record)
  assert.deepEqual(layout.basic, summary.slice(0, 4))
  assert.deepEqual(layout.lines, summary.slice(4))
  assert.equal(layout.lines[0], summary[4])
  assert.equal(layout.showLines, true)
  assert.deepEqual(record, before)
})

// 空响应不显示物料表，其他领域不能因标签相似而丢失附件或财务摘要。
test('未读到记录与无物料领域安全回退，空物料明细仍由公共只读表格提示', () => {
  assert.deepEqual(documentApprovalLayout(null), { basic: [], lines: [], showLines: false })
  const summary = [{ label: '仓库', value: '现场依据' }, { label: '附件依据', value: '原始指纹' }]
  assert.deepEqual(documentApprovalLayout({ document_type: 'Journal', summary }), { basic: summary, lines: [], showLines: false })
  assert.deepEqual(documentApprovalLayout({ document_type: 'WarehouseInbound', summary: [] }), { basic: [], lines: [], showLines: true })
})

// 计划产品只从送审摘要分组，重复产品、旧服务原文和未知摘要均不得丢失。
test('生产计划基础信息与产品表分开，结构字段和旧原文保持不变', () => {
  const summary = [{label:'计划名称',value:'六月计划'}, {label:'计划产品',value:'旧服务完整文字'},
    {label:'计划产品',value:'固定新明细',production_plan_line:{sku:'OLD-001',name:'送审名称'}}, {label:'历史依据',value:'保留'}]
  const before = structuredClone(summary)
  const result = documentApprovalLayout({document_type:'ProductionPlan',summary})
  assert.deepEqual(result.basic, [summary[0],summary[3]])
  assert.deepEqual(result.lines, [summary[1],summary[2]])
  assert.equal(result.lines[1],summary[2])
  assert.equal(result.showLines,true)
  assert.deepEqual(summary,before)
})
