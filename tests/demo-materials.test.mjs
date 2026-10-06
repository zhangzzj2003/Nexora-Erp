import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { materialBody } from '../src/shared/material-validation.ts'

const rows = JSON.parse(readFileSync(new URL('../scripts/demo/materials.json', import.meta.url), 'utf8'))

test('五十条演示物料覆盖现有各类，并具有稳定的独立示例标识', () => {
  assert.equal(rows.length, 50)
  assert.equal(new Set(rows.map(row => row.manufacturer_part_number)).size, rows.length)
  assert.equal(new Set(rows.map(row => row.name)).size, rows.length)
  // 子类以正式服务端目录为准，扩展或调整目录时提醒同步假数据。
  const taxonomy = readFileSync(new URL('../backend/app/catalog/material_rules.py', import.meta.url), 'utf8')
  const codes = [...taxonomy.matchAll(/"code": "([A-Z]{2}-[A-Z]{2})"/g)].map(match => match[1])
  assert.deepEqual(new Set(rows.map(row => row.category_code)), new Set(codes))
  assert.deepEqual(Object.fromEntries(['EL', 'HW', 'PL', 'PK', 'OT'].map(group =>
    [group, rows.filter(row => row.category_code.startsWith(group + '-')).length])),
  { EL: 24, HW: 14, PL: 5, PK: 4, OT: 3 })
  for (const row of rows) {
    assert.ok(row.name.startsWith('示例 · '))
    assert.ok(row.manufacturer_part_number.startsWith('DEMO-'))
    assert.match(row.notes, /NEXORA-DEMO-MATERIALS-V1/)
    assert.ok(row.specification && row.unit)
    assert.equal('sku' in row, false)
    assert.equal('quantity' in row, false)
  }
})

test('演示物料遵循现有写入契约，电子参数按具体品种填写', () => {
  for (const row of rows) assert.deepEqual(materialBody(row), row)
  const resistor = rows.find(row => row.manufacturer_part_number === 'DEMO-R10K-0603')
  assert.equal(resistor.electrical_value, '10kΩ')
  assert.equal(resistor.tolerance, '±1%')
  assert.equal(resistor.rated_power, '0.1W')
  // 五金和包装不填写无关电气参数，避免测试数据误导表单展示。
  for (const row of rows.filter(row => !row.category_code.startsWith('EL-'))) {
    assert.equal(row.rated_voltage, '')
    assert.equal(row.rated_power, '')
  }
})
