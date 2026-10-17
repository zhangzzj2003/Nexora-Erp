import assert from 'node:assert/strict'
import { test } from 'node:test'
import { materialParameterIndex, materialParameterSource } from '../src/renderer/src/utils/material-parameter-source.ts'

// 编号或名称相同也不能作为物料身份，缓存只为旧响应回退，不产生请求或写入。
test('参数优先取本行真实身份，旧响应只按物料 ID 回退', () => {
  const current = { id: 1, sku: 'DUP', name: '同名', unit: '个', specification: '当前档案规格' }
  const cached = { ...current, specification: '缓存规格' }, other = { ...current, id: 2, specification: '其他物料规格' }
  const index = materialParameterIndex([cached, other])
  assert.equal(materialParameterSource(1, current, index), current)
  assert.equal(materialParameterSource(1, undefined, index), cached)
  assert.equal(materialParameterSource(1, other, index), cached)
  assert.equal(materialParameterSource(3, other, index), undefined)
  for (const invalid of [0,-1,NaN,Infinity,1.5,'1',null]) assert.equal(materialParameterSource(invalid,current,index), undefined)
  assert.equal(materialParameterSource(1,current,new Map()), current)
  assert.equal(materialParameterSource(1,undefined,new Map([[1, other]])), undefined)
  assert.deepEqual([current.specification,cached.specification,other.specification], ['当前档案规格','缓存规格','其他物料规格'])
})
