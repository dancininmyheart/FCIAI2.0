# FCI AI 2.0 - 文件翻译系统

FCI AI 2.0 提供 PowerPoint 与 PDF 翻译。现有 HTTP 路由、任务字段、PPT 翻译模式、选页行为和 PDF 输出 DOCX 的产品契约保持不变；翻译执行已拆分为 Web 与 Worker 两种运行角色。

## 主要能力

- PPT/PPTX：按页翻译、仅译文/双语模式、词库与停翻词、图片 OCR、选页写回、文本框自动适配。
- PDF：MinerU/本地解析、可选 OCR、Qwen/DeepSeek 模型路由、双语 DOCX 输出。
- 任务：数据库任务账本、原子领取、重试/取消、重启后状态投影、不可变源文件和幂等产物发布。
- 翻译：显式 Provider Adapter、稳定 Translation Unit、结构质量检查、单次定向重试、重复文本合并、受控并发和可选翻译记忆。
- 运维：关联 ID、脱敏结构化日志、阶段/Provider/质量/缓存指标和鉴权健康接口。

详细设计见 [翻译架构](docs/TRANSLATION_ARCHITECTURE.md)，完整功能盘点见 [项目架构与需求](docs/PROJECT_ARCHITECTURE_AND_REQUIREMENTS.md)。

## 环境要求

- Python 3.11（当前 Windows 安装脚本的目标版本）
- MySQL 8
- LibreOffice（PPT 渲染、旧 `.ppt` 转换和版式验收需要）
- Redis 可选；当前应用默认使用进程内翻译记忆，持久化任务状态仍由 MySQL 提供
- Qwen/DeepSeek、MinerU、OSS 等外部服务按实际功能配置

安装依赖：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

新增任务表采用非破坏式迁移：

```powershell
python migrations/add_translation_jobs.py upgrade --database-url "mysql+pymysql://user:password@host/database"
```

## 启动方式

开发环境使用一个命令启动 Web 和内嵌 Worker：

```powershell
python run.py
```

`run.py` 同时承载 Web 和内嵌 Worker，因此开发服务器会关闭 Flask 自动重载，避免代码重载进程重复启动 Worker。修改代码后请手动重启服务。

生产环境必须分别启动一个 Web 入口和一个 Worker。Web 可选择 WSGI 或 ASGI 包装入口：

```powershell
python app.py
python run_worker.py
```

或：

```powershell
python run_async.py
python run_worker.py
```

不要在多个 Web 进程中内嵌启动 Worker。`quick_install.bat` 和 `quick_install.sh` 已按一个 Web 加一个 Worker 配置。

所有入口均支持无副作用装配检查：

```powershell
python run.py --check
python app.py --check
python run_async.py --check
python run_worker.py --check
```

数据库 SQL 默认不输出到控制台，避免内嵌 Worker 的队列轮询持续打印 `SELECT` 和只读事务结束时的 `ROLLBACK`。仅在排查数据库问题时临时开启：

```dotenv
SQLALCHEMY_ECHO=false
LOG_LEVEL_SQLALCHEMY=WARNING
```

将 `SQLALCHEMY_ECHO` 改为 `true` 并重启后可查看完整 SQL；排查完成后应恢复为 `false`。

## 翻译开关

代码默认值保持兼容模式：

```dotenv
TRANSLATION_ARCH_MODE=legacy
TRANSLATION_QUALITY_MODE=off
TRANSLATION_MEMORY_ENABLED=0
TRANSLATION_AUTO_RECOVER=0
QWEN_MODEL=qwen3.7-plus
PPTX_XML_ENGINE=structured_v2
PPTX_XML_RUNTIME_FALLBACK=0
```

建议先使用观察模式上线：

```dotenv
TRANSLATION_ARCH_MODE=v2
TRANSLATION_QUALITY_MODE=observe
TRANSLATION_MEMORY_ENABLED=1
TRANSLATION_AUTO_RECOVER=0
QWEN_MODEL=qwen3.7-plus
PPTX_XML_ENGINE=structured_v2
PPTX_XML_RUNTIME_FALLBACK=0
```

`TRANSLATION_ARCH_MODE` 控制任务编排版本，`PPTX_XML_ENGINE` 独立控制 `.pptx` 的提取和写回方式。`structured_v2` 直接处理底层 XML；`PPTX_XML_RUNTIME_FALLBACK=0` 会让 Provider 或结构化协议错误直接结束任务，不再静默进入旧版 `[block]`/UNO 翻译路径。只有在明确接受版式风险时，才可临时把运行时回退设为 `1`，该回退仅处理允许降级的 ZIP、XML、包或不支持结构错误。

Qwen 默认使用 `qwen3.7-plus`，并在翻译时关闭思考模式。PPTX 结构化请求会额外启用 JSON Object 输出模式。修改上述开关后，必须同时重启 Web 与 Worker，确保任务进程读取到相同配置。

观察指标和产物稳定后，可将 `TRANSLATION_QUALITY_MODE` 改为 `enforce`。出现回归时，恢复上面的默认值并重启 Web 与 Worker；回滚不需要删除任务表或产物。

鉴权用户可访问 `GET /api/translation/health`。普通用户只看到自己的任务汇总，管理员可以看到全局汇总；接口不返回任务 ID、源文本或密钥。

## 文件大小

完整应用当前 `MAX_CONTENT_LENGTH` 为 12 GiB。Nginx、网关、磁盘容量、请求超时和用户配额必须同时满足实际上传上限；生产环境应按部署容量主动下调，而不是只修改前端提示。支持 `.ppt`、`.pptx` 和 `.pdf`。

## 验证

```powershell
python -m pytest -q
python tools/qa/benchmark_translation_architecture.py --root D:\project\FCIAI2.0 --output .omo/evidence/benchmark.json
```

真实 PPT 的确定性版式验收：

```powershell
python tools/qa/run_translation_acceptance.py --root D:\project\FCIAI2.0 --provider deterministic --ppt "C:\Users\48846\Documents\FINAL_Role of HMOs in Preterm Nutrition Presentation_3.pptx" --libreoffice "C:\Program Files\LibreOffice\program\soffice.exe" --output .omo\evidence\translation-acceptance
```

验收过程复制源文件后再处理，不修改原始演示文稿。
