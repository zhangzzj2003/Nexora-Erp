import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'

export function selectBackendPython(cwd, platform = process.platform, env = process.env,
  fileExists = existsSync) {
  if (env.NEXORA_PYTHON) return env.NEXORA_PYTHON
  // 优先使用项目虚拟环境，避免系统 Python 缺依赖却仍打出无法启动的服务程序。
  const virtualPython = join(cwd, '.venv', ...(platform === 'win32'
    ? ['Scripts', 'python.exe'] : ['bin', 'python']))
  return fileExists(virtualPython) ? virtualPython : (platform === 'win32' ? 'python' : 'python3')
}

export function checkBackendBuildEnvironment(python, platform = process.platform,
  run = spawnSync) {
  const modules = ['fastapi', 'uvicorn', 'cryptography', 'zeroconf', 'ifaddr', 'reportlab', 'PyInstaller']
  if (platform === 'win32') modules.push('servicemanager', 'win32service', 'win32serviceutil')
  // 逐个实际导入运行依赖，PyInstaller 的成功退出本身不能证明隐藏依赖已被打入包内。
  const probe = `import importlib, sys\nif sys.version_info < (3, 11):\n raise RuntimeError('Python 3.11+ required')\nfor name in ${JSON.stringify(modules)}:\n importlib.import_module(name)`
  const result = run(python, ['-c', probe], { encoding: 'utf8' })
  if (result.error || result.status !== 0) {
    const detail = result.error?.message || result.stderr?.trim() || `退出码 ${result.status}`
    throw new Error(`所选 Python 无法导入服务打包依赖：${detail}\n请为该 Python 安装 backend/requirements-dev.txt 和 PyInstaller，或设置 NEXORA_PYTHON。`)
  }
}
