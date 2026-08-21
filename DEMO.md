# PPT Agent Studio 部署与使用指南

PPT Agent Studio 是一个面向 PowerPoint 的智能翻译应用。用户可以上传 `.ppt` 或 `.pptx` 文件，配置语言、翻译模式、页码范围与模型 Provider，并在任务完成后下载可编辑的翻译文件。

## 1. 准备环境

推荐使用 Python 3.11。旧 `.ppt` 转换、渲染与版式验收依赖 LibreOffice；本地一体化运行不要求预先安装 MySQL。

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.demo.example .env
```

编辑 `.env`：

1. 为 `SECRET_KEY` 设置高熵随机值；仅限本机临时运行时可留空并由进程生成。
2. 为 `DEMO_ACCESS_PASSWORD` 设置不少于 12 个字符的唯一随机强密码。
3. 至少配置 Qwen 或 DeepSeek 中的一个 Provider。
4. Windows 若未自动发现 LibreOffice，设置 `LIBREOFFICE_PATH` 为安装根目录。
5. 保持 `SSO_ENABLED=false`，使用内置访问账户登录。

登录保护配置：

```dotenv
DEMO_ACCESS_USERNAME=demo
DEMO_ACCESS_PASSWORD=
DEMO_LOGIN_MAX_ATTEMPTS=5
DEMO_LOGIN_LOCKOUT_SECONDS=300
```

`DEMO_ACCESS_USERNAME` 默认为 `demo`。示例密码故意留空；密码未配置或少于 12 个字符时，服务仍可启动，但会拒绝登录。连续失败默认达到 5 次后锁定当前浏览器会话 300 秒。重启服务或轮换密码后需要重新登录。

## 2. 本地启动

先检查装配：

```powershell
python run.py --demo --check
```

再启动 Web 服务与内嵌 Worker：

```powershell
python run.py --demo
```

浏览器访问 `http://127.0.0.1:5000`，输入 `.env` 中配置的用户名和密码即可进入 PPT 翻译工作台。

`--demo` 是本地一体化运行模式的技术参数。该模式默认将任务账本写入系统临时目录中的 `ppt-agent-studio/demo.sqlite3`，并在相关变量未设置时启用 V2 编排、翻译记忆、结构与语义质量检查以及可编辑写回。可通过 `DEMO_DATABASE_PATH` 指定另一个 SQLite 文件。

## 3. Provider 配置

### Qwen

```dotenv
QWEN_API_KEY=replace-with-your-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.7-plus
```

### DeepSeek

```dotenv
DEEPSEEK_API_KEY=replace-with-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

两个 Provider 都使用 OpenAI-compatible 接口。API Key 只应保存在未纳入版本控制的 `.env` 或部署平台的密钥管理服务中。

使用真实 Provider 时，PPT 中的待译文本会发送到对应服务。请仅处理有权使用且不含敏感信息的文件，并确认相应服务的数据处理条款。

## 4. 使用流程

1. 登录应用，进入 **PPT 翻译**。
2. 上传 `.ppt` 或 `.pptx` 文件。
3. 选择源语言、目标语言、仅译文或双语模式。
4. 按需设置页码范围、OCR 与模型 Provider。
5. 选择 **开始翻译**，在任务状态区查看排队、处理、检查与完成状态。
6. 任务完成后下载并打开结果文件，重点复核组合图形、小型文本框、SmartArt 与字体替换可能影响的页面。

系统会将 PPTX 拆成带稳定标识的翻译单元，校验 Provider 返回的结构，并对失败单元执行一次定向修复。候选文件通过包完整性与质量检查后才会发布。该流程能降低结构错位和版式破坏风险，但不能保证任意文件完全保持原版式，也不能替代人工语言审校。

## 5. 数据库与长期运行

本地一体化模式使用 SQLite，适合单进程运行。多进程或长期运行部署可配置 MySQL：

```dotenv
DB_TYPE=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=ppt_agent_studio
DB_USER=ppt_agent
DB_PASSWORD=replace-with-your-password
```

配置后使用常规入口启动；不要附加 `--demo`：

```powershell
python run.py
```

如需单独执行非破坏式任务表迁移：

```powershell
python migrations/add_translation_jobs.py upgrade --database-url "mysql+pymysql://ppt_agent:password@127.0.0.1/ppt_agent_studio"
```

## 6. 公网部署安全

- 为 `SECRET_KEY` 与登录密码设置独立、高熵的随机值，并通过部署平台密钥管理功能注入。
- 在反向代理或网关终止 TLS，不要通过明文 HTTP 传输登录凭据或 PPT 内容。
- 在网络层按来源 IP 配置登录限流和访问控制。应用内失败锁定基于浏览器 Cookie/会话，不能抵御分布式尝试或更换 Cookie。
- 不要在日志、截图或错误报告中暴露 API Key、密码、内网地址、绝对路径或 PPT 原文。
- 为数据库和模型 Provider 使用最小权限凭据，并定期轮换。
- 正式对外提供服务前，应独立完成许可证、安全、隐私与数据合规审查。

## 7. 常见故障

### 登录按钮不可用

确认 `DEMO_ACCESS_PASSWORD` 已设置且不少于 12 个字符，然后重启服务。`DEMO_` 前缀是现有运行模式的兼容配置命名。

### Provider 请求立即失败

核对 API Key、Base URL、模型名称、账户余额与网络连接。不要把完整 Key 粘贴到错误报告或截图中。

### 数据库连接失败

核对 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER` 和 `DB_PASSWORD`，并确认数据库已创建且账号拥有对应库的最小必要权限。

### 旧 `.ppt` 无法处理或渲染失败

确认 LibreOffice 已安装。Windows 的 `LIBREOFFICE_PATH` 应指向安装根目录，而不是 `soffice.exe` 文件本身。

### 下载文件存在局部拥挤

先尝试较短译文或仅译文模式。组合图形、极小文本框、SmartArt 与字体缺失需要重点人工检查；文件可打开不等同于视觉效果完全通过。
