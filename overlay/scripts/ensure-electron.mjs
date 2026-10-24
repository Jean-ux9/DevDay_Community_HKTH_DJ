// pnpm can link electron without running its install script (e.g. a reused store, or a pnpm that
// ignores `allowBuilds`). Then there is no binary and electron-vite fails with "Electron uninstall".
// Run electron's own installer when that happens; it uses the shared download cache when it can.
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

const require = createRequire(import.meta.url)
const dir = dirname(require.resolve('electron/package.json'))
const pathFile = join(dir, 'path.txt')
const installed = existsSync(pathFile) && existsSync(join(dir, 'dist', readFileSync(pathFile, 'utf8').trim()))
if (!installed) {
  console.log('Electron binary missing; running its installer…')
  execFileSync(process.execPath, [join(dir, 'install.js')], { cwd: dir, stdio: 'inherit' })
}
