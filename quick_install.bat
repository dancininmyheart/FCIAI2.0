@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: PPT翻译系统Windows快速安装脚本
title PPT翻译系统 - 快速安装

echo ==========================================
echo   PPT翻译系统 Windows 快速安装脚本
echo ==========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本
    pause
    exit /b 1
)

:: 设置变量
set PYTHON_VERSION=3.11.7
set MYSQL_VERSION=8.0.35
set PROJECT_DIR=%~dp0
set VENV_DIR=%PROJECT_DIR%venv

echo [信息] 项目目录: %PROJECT_DIR%
echo [信息] 虚拟环境目录: %VENV_DIR%
echo.

:: 检查Python安装
echo [步骤 1/8] 检查Python安装...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] Python未安装或未添加到PATH
    echo [信息] 请从 https://python.org 下载并安装Python %PYTHON_VERSION%
    echo [信息] 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
) else (
    for /f "tokens=2" %%i in ('python --version') do set CURRENT_PYTHON=%%i
    echo [信息] 当前Python版本: !CURRENT_PYTHON!
    python -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 11) else 1)"
    if !errorLevel! neq 0 (
        echo [错误] 需要Python 3.11或更高版本
        pause
        exit /b 1
    )
)

:: 检查pip
echo [步骤 2/8] 检查pip...
pip --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] pip未安装
    echo [信息] 请重新安装Python并确保包含pip
    pause
    exit /b 1
)

:: 创建虚拟环境
echo [步骤 3/8] 创建Python虚拟环境...
if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
    if %errorLevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [信息] 虚拟环境创建成功
) else (
    echo [信息] 虚拟环境已存在，跳过创建
)

:: 激活虚拟环境并安装依赖
echo [步骤 4/8] 安装Python依赖包...
call "%VENV_DIR%\Scripts\activate.bat"
if %errorLevel% neq 0 (
    echo [错误] 激活虚拟环境失败
    pause
    exit /b 1
)

:: 升级pip
python -m pip install --upgrade pip

:: 安装依赖
if exist "requirements.txt" (
    echo [信息] 正在安装依赖包，这可能需要几分钟...
    pip install -r requirements.txt
    if %errorLevel% neq 0 (
        echo [错误] 安装依赖包失败
        echo [信息] 请检查网络连接或手动安装依赖
        pause
        exit /b 1
    )
    echo [信息] 依赖包安装完成
) else (
    echo [错误] requirements.txt 文件不存在
    pause
    exit /b 1
)

:: 验证所有运行入口，只检查装配，不启动监听器或后台任务
echo [信息] 验证运行入口...
for %%e in (run.py app.py run_async.py run_worker.py) do (
    python %%e --check
    if !errorLevel! neq 0 (
        echo [错误] %%e --check 失败
        pause
        exit /b 1
    )
)

:: 检查MySQL
echo [步骤 5/8] 检查MySQL安装...
mysql --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] MySQL未安装或未添加到PATH
    echo [信息] 请从以下地址下载并安装MySQL:
    echo [信息] https://dev.mysql.com/downloads/mysql/
    echo [信息] 或使用XAMPP: https://www.apachefriends.org/
    echo.
    set /p mysql_choice="是否已安装MySQL但未添加到PATH? (y/N): "
    if /i "!mysql_choice!"=="y" (
        echo [信息] 请手动配置MySQL PATH或使用完整路径
    ) else (
        echo [信息] 请安装MySQL后重新运行此脚本
        pause
        exit /b 1
    )
) else (
    echo [信息] MySQL已安装
)

:: 创建必要目录
echo [步骤 6/8] 创建必要目录...
if not exist "uploads" mkdir uploads
if not exist "uploads\ppt" mkdir uploads\ppt
if not exist "uploads\pdf" mkdir uploads\pdf
if not exist "uploads\annotation" mkdir uploads\annotation
if not exist "uploads\temp" mkdir uploads\temp
if not exist "logs" mkdir logs
if not exist "static\uploads" mkdir static\uploads
echo [信息] 目录创建完成

:: 配置数据库
echo [步骤 7/8] 配置数据库...
if exist "setup_database.py" (
    echo [信息] 运行数据库初始化脚本...
    python setup_database.py
    if %errorLevel% neq 0 (
        echo [警告] 数据库初始化可能失败，请检查MySQL连接
    )
) else (
    echo [警告] setup_database.py 文件不存在，请手动配置数据库
)

:: 创建启动脚本
echo [步骤 8/8] 创建启动脚本...

:: 创建开发模式启动脚本
echo @echo off > start_dev.bat
echo chcp 65001 ^>nul >> start_dev.bat
echo title PPT翻译系统 - 开发模式 >> start_dev.bat
echo echo 启动PPT翻译系统（开发模式）... >> start_dev.bat
echo cd /d "%PROJECT_DIR%" >> start_dev.bat
echo call "%VENV_DIR%\Scripts\activate.bat" >> start_dev.bat
echo python run.py >> start_dev.bat
echo pause >> start_dev.bat

:: 创建生产 Web 入口
echo @echo off > start_web.bat
echo chcp 65001 ^>nul >> start_web.bat
echo cd /d "%PROJECT_DIR%" >> start_web.bat
echo call "%VENV_DIR%\Scripts\activate.bat" >> start_web.bat
echo python run_async.py >> start_web.bat

:: 创建生产 Worker 入口
echo @echo off > start_worker.bat
echo chcp 65001 ^>nul >> start_worker.bat
echo cd /d "%PROJECT_DIR%" >> start_worker.bat
echo call "%VENV_DIR%\Scripts\activate.bat" >> start_worker.bat
echo python run_worker.py >> start_worker.bat

:: 创建生产模式启动脚本：一个 Web 进程和一个 Worker 进程
echo @echo off > start_prod.bat
echo chcp 65001 ^>nul >> start_prod.bat
echo title PPT翻译系统 - 生产模式 >> start_prod.bat
echo echo 启动PPT翻译系统（生产模式）... >> start_prod.bat
echo cd /d "%PROJECT_DIR%" >> start_prod.bat
echo if not exist logs mkdir logs >> start_prod.bat
echo powershell -NoProfile -Command "$files = @('%PROJECT_DIR%logs\web.pid', '%PROJECT_DIR%logs\worker.pid'); foreach ($file in $files) { if (Test-Path -LiteralPath $file) { $processId = [int](Get-Content -LiteralPath $file); if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { Write-Error ('System already running, pid=' + $processId); exit 1 }; Remove-Item -LiteralPath $file -Force } }" >> start_prod.bat
echo if errorlevel 1 exit /b 1 >> start_prod.bat
echo powershell -NoProfile -Command "$started = @(); try { $web = Start-Process -FilePath '%VENV_DIR%\Scripts\python.exe' -ArgumentList 'run_async.py' -WorkingDirectory '%PROJECT_DIR%' -WindowStyle Hidden -RedirectStandardOutput '%PROJECT_DIR%logs\web.out.log' -RedirectStandardError '%PROJECT_DIR%logs\web.err.log' -PassThru; $started += $web; $worker = Start-Process -FilePath '%VENV_DIR%\Scripts\python.exe' -ArgumentList 'run_worker.py' -WorkingDirectory '%PROJECT_DIR%' -WindowStyle Hidden -RedirectStandardOutput '%PROJECT_DIR%logs\worker.out.log' -RedirectStandardError '%PROJECT_DIR%logs\worker.err.log' -PassThru; $started += $worker; Set-Content -LiteralPath '%PROJECT_DIR%logs\web.pid' -Value $web.Id; Set-Content -LiteralPath '%PROJECT_DIR%logs\worker.pid' -Value $worker.Id } catch { foreach ($process in $started) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }; Remove-Item -LiteralPath '%PROJECT_DIR%logs\web.pid', '%PROJECT_DIR%logs\worker.pid' -Force -ErrorAction SilentlyContinue; throw }" >> start_prod.bat
echo if errorlevel 1 exit /b 1 >> start_prod.bat
echo echo Web 与 Worker 已启动。 >> start_prod.bat

:: 创建停止脚本
echo @echo off > stop.bat
echo chcp 65001 ^>nul >> stop.bat
echo title 停止PPT翻译系统 >> stop.bat
echo echo 正在停止PPT翻译系统... >> stop.bat
echo powershell -NoProfile -Command "$files = @('%PROJECT_DIR%logs\web.pid', '%PROJECT_DIR%logs\worker.pid'); foreach ($file in $files) { if (Test-Path -LiteralPath $file) { $processId = [int](Get-Content -LiteralPath $file); Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $file -Force } }" >> stop.bat
echo echo 系统已停止 >> stop.bat
echo pause >> stop.bat

:: 创建状态检查脚本
echo @echo off > status.bat
echo chcp 65001 ^>nul >> status.bat
echo title PPT翻译系统状态 >> status.bat
echo echo ==================== >> status.bat
echo echo   PPT翻译系统状态检查 >> status.bat
echo echo ==================== >> status.bat
echo echo. >> status.bat
echo echo 受管进程: >> status.bat
echo powershell -NoProfile -Command "$roles = @('web', 'worker'); foreach ($role in $roles) { $file = '%PROJECT_DIR%logs\' + $role + '.pid'; if (Test-Path -LiteralPath $file) { $processId = [int](Get-Content -LiteralPath $file); $process = Get-Process -Id $processId -ErrorAction SilentlyContinue; if ($process) { Write-Host ($role + ': running, pid=' + $processId) } else { Write-Host ($role + ': stopped (stale pid file)') } } else { Write-Host ($role + ': stopped') } }" >> status.bat
echo echo. >> status.bat
echo echo 端口占用情况: >> status.bat
echo netstat -an ^| find ":5000" >> status.bat
echo echo. >> status.bat
echo pause >> status.bat

echo [信息] 启动脚本创建完成

:: 创建环境配置文件
if not exist ".env" (
    echo [信息] 创建环境配置文件...
    echo # 数据库配置 > .env
    echo DB_TYPE=mysql >> .env
    echo DB_HOST=localhost >> .env
    echo DB_PORT=3306 >> .env
    echo DB_USER=root >> .env
    echo DB_PASSWORD=password >> .env
    echo DB_NAME=ppt_translate_db >> .env
    echo. >> .env
    echo # Flask配置 >> .env
    echo SECRET_KEY=your-secret-key-here >> .env
    echo FLASK_ENV=production >> .env
    echo FLASK_DEBUG=False >> .env
    echo. >> .env
    echo # 日志配置 >> .env
    echo SQLALCHEMY_ECHO=false >> .env
    echo LOG_LEVEL_SQLALCHEMY=WARNING >> .env
    echo. >> .env
    echo # 上传配置 >> .env
    echo UPLOAD_FOLDER=uploads >> .env
    echo MAX_CONTENT_LENGTH=52428800 >> .env
    echo. >> .env
    echo # API配置 >> .env
    echo DASHSCOPE_API_KEY=your-dashscope-api-key >> .env
    echo QWEN_API_KEY=your-dashscope-api-key >> .env
    echo QWEN_MODEL=qwen3.7-plus >> .env
    echo. >> .env
    echo # PPTX结构化翻译配置 >> .env
    echo PPTX_XML_ENGINE=structured_v2 >> .env
    echo PPTX_XML_RUNTIME_FALLBACK=0 >> .env
    echo PPTX_SEMANTIC_QA_MODE=enforce >> .env
    echo PPTX_XML_AUTOFIT_POLICY=editable >> .env
    echo [信息] 请编辑 .env 文件配置相关参数
)

:: 显示安装结果
echo.
echo ==========================================
echo           安装完成！
echo ==========================================
echo.
echo 🎉 PPT翻译系统安装成功！
echo.
echo 📁 项目目录: %PROJECT_DIR%
echo 🐍 Python环境: %VENV_DIR%
echo.
echo 🚀 启动方式:
echo   开发模式: 双击 start_dev.bat
echo   生产模式: 双击 start_prod.bat
echo.
echo 🔧 管理脚本:
echo   停止系统: 双击 stop.bat
echo   查看状态: 双击 status.bat
echo.
echo 🌐 访问地址: http://localhost:5000
echo 👤 管理员账户: admin
echo 🔑 管理员密码: admin123
echo.
echo 📋 重要提醒:
echo   1. 请立即修改默认管理员密码
echo   2. 编辑 .env 文件配置API密钥
echo   3. 确保MySQL服务正在运行
echo   4. 如遇问题请查看 logs 目录下的日志文件
echo.
echo 📖 详细文档: DEPLOYMENT_GUIDE.md
echo.

:: 询问是否立即启动
set /p start_now="是否立即启动系统? (Y/n): "
if /i "!start_now!"=="n" (
    echo [信息] 稍后可双击 start_dev.bat 启动系统
) else (
    echo [信息] 正在启动系统...
    start "" "%PROJECT_DIR%start_dev.bat"
)

echo.
echo 安装脚本执行完成！
pause
