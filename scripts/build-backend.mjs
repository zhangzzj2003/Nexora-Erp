import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { checkBackendBuildEnvironment, selectBackendPython } from './backend-build-env.mjs'

// 构建缓存放在仓库的忽略目录，Mac 与 Windows 都不依赖用户级缓存写权限。
const cache = join(process.cwd(), 'build', 'pyinstaller-cache')
mkdirSync(cache, { recursive: true })
const python = selectBackendPython(process.cwd())
const dataSeparator = process.platform === 'win32' ? ';' : ':'
const quoteFontSource = join(process.cwd(), 'backend', 'app', 'sales', 'fonts')
try {
  checkBackendBuildEnvironment(python)
} catch (error) {
  console.error(error.message)
  process.exit(1)
}
const result = spawnSync(python, ['-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
  '--collect-all', 'tzdata',
  '--name', 'nexora-server', '--distpath', 'build', '--workpath', 'build/pyinstaller',
  '--add-data', `${quoteFontSource}${dataSeparator}app/sales/fonts`,
  '--specpath', 'build/pyinstaller', 'backend/launcher.py'], {
  stdio: 'inherit', env: { ...process.env, PYINSTALLER_CONFIG_DIR: cache }
})
if (result.error) throw result.error
process.exit(result.status ?? 1)
