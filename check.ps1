# agent1 一键检查：后端 ruff + 七层依赖 + 导入/表数；前端 ESLint + 构建
# 用法：在项目根目录执行 .\check.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$fail = 0

Write-Host "===== [1/5] 后端 ruff =====" -ForegroundColor Cyan
Push-Location "$root\backend"
.\venv\Scripts\python.exe -m ruff check app scripts worker.py promote_admin.py run.py
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host "===== [2/5] 后端七层依赖检查 =====" -ForegroundColor Cyan
.\venv\Scripts\python.exe scripts\check_layers.py
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host "===== [3/5] 后端关键模块导入 + 表数断言 =====" -ForegroundColor Cyan
.\venv\Scripts\python.exe -c "from app.core.db.base import Base; import app.models.db_models, app.models.schemas; from app import tasks; from app.planning import graph; import app.api.main; assert len(Base.metadata.tables) == 24, 'table count changed'; print('import ok, tables =', len(Base.metadata.tables))"
if ($LASTEXITCODE -ne 0) { $fail = 1 }
Pop-Location

Write-Host "===== [4/5] 前端 ESLint =====" -ForegroundColor Cyan
Push-Location "$root\frontend"
npm.cmd run lint
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host "===== [5/5] 前端构建（vue-tsc + vite）=====" -ForegroundColor Cyan
npm.cmd run build
if ($LASTEXITCODE -ne 0) { $fail = 1 }
Pop-Location

if ($fail) { Write-Host "`nCHECK FAILED" -ForegroundColor Red; exit 1 }
Write-Host "`nALL CHECKS PASSED" -ForegroundColor Green
