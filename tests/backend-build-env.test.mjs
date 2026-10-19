import assert from 'node:assert/strict'
import { test } from 'node:test'
import { join } from 'node:path'
import { checkBackendBuildEnvironment, selectBackendPython } from '../scripts/backend-build-env.mjs'

test('服务打包优先选项目虚拟环境，显式指定仍优先', () => {
  const cwd = '/project'
  assert.equal(selectBackendPython(cwd, 'darwin', {}, (path) => path === join(cwd, '.venv', 'bin', 'python')),
    join(cwd, '.venv', 'bin', 'python'))
  assert.equal(selectBackendPython(cwd, 'win32', {}, (path) => path === join(cwd, '.venv', 'Scripts', 'python.exe')),
    join(cwd, '.venv', 'Scripts', 'python.exe'))
  assert.equal(selectBackendPython(cwd, 'darwin', { NEXORA_PYTHON: '/custom/python' }, () => true),
    '/custom/python')
  assert.equal(selectBackendPython(cwd, 'win32', {}, () => false), 'python')
})

test('缺少运行依赖时在打包前明确失败，Windows 同时检查服务模块', () => {
  const calls = []
  const run = (python, args, options) => {
    calls.push({ python, args, options })
    return { status: 1, stderr: "ModuleNotFoundError: No module named 'ifaddr'" }
  }
  assert.throws(() => checkBackendBuildEnvironment('python', 'win32', run),
    /No module named 'ifaddr'[\s\S]*NEXORA_PYTHON/)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].args[0], '-c')
  assert.match(calls[0].args[1], /Python 3\.11\+ required/)
  assert.match(calls[0].args[1], /importlib\.import_module\(name\)/)
  assert.match(calls[0].args[1], /win32serviceutil/)
  assert.match(calls[0].args[1], /ifaddr/)
  // 防止仓库自动编码依赖仅存在于开发环境，打包却遗漏启动所需模块。
  assert.match(calls[0].args[1], /pypinyin/)
})

test('依赖齐全时允许继续打包，解释器启动失败也给出诊断', () => {
  assert.doesNotThrow(() => checkBackendBuildEnvironment('python', 'darwin', () => ({ status: 0 })))
  assert.throws(() => checkBackendBuildEnvironment('missing-python', 'darwin',
    () => ({ error: new Error('ENOENT'), status: null })), /ENOENT/)
})
