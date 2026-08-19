# PPT Agent Studio 面试 Demo 指南

这份指南用于在本地把项目演示为一个匿名化的 PPT 翻译 Agent。推荐准备一份 3–5 页、内容自制或已获授权的 `.pptx`，并提前完成一次全流程预演。

## 1. 准备环境

安装 Python 3.11、MySQL 8 和 LibreOffice，然后在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.demo.example .env
```

编辑 `.env`：

1. 替换 `SECRET_KEY`。
2. 至少配置 Qwen 或 DeepSeek 中的一个 Provider。
3. Windows 若未自动发现 LibreOffice，设置 `LIBREOFFICE_PATH` 为安装根目录。
4. 保持 `SSO_ENABLED=false`，避免进入任何外部身份系统。

`--demo` 默认把任务账本放在系统临时目录的 `ppt-agent-studio/demo.sqlite3`，不要求 MySQL。它也会在相关变量未设置时启用 V2 编排、翻译记忆、结构/语义质量门和可编辑写回；显式环境变量仍可用于对比或回滚。若需自定义位置，可设置 `DEMO_DATABASE_PATH`；路径必须指向一个 SQLite 文件，而不是目录。

启动前检查装配：

```powershell
python run.py --demo --check
```

启动 Web 与本地内嵌 Worker：

```powershell
python run.py --demo
```

浏览器访问 `http://127.0.0.1:5000`，点击“进入演示工作区”。系统会在隔离的 Demo 数据库中创建一个无共享密码的本地访客身份。

## 2. Provider 配置

### Qwen

```dotenv
QWEN_API_KEY=replace-with-your-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.7-plus
```

结构化 PPTX 路径通过 DashScope 的 OpenAI-compatible API 请求 JSON Object 输出。API Key 只保存在未跟踪的 `.env` 中。

### DeepSeek

```dotenv
DEEPSEEK_API_KEY=replace-with-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

两个 Provider 都使用 OpenAI-compatible 接口。建议使用自己的服务配置，并在正式录屏前确认模型名、Base URL 和余额。

### 数据库

Demo 的 SQLite 和常规部署的 MySQL 使用同一套 SQLAlchemy 模型与任务账本语义。要演示 MySQL，请在 MySQL 中创建一个独立空库和最小权限账号，填写 `.env.demo.example` 中的 `DB_*` 变量，然后运行：

```powershell
python run.py
```

不要复用公司的数据库、账号或备份。注意，不带 `--demo` 时不会启用匿名访客入口，需要使用应用的常规本地登录方式。

### 数据注意事项

选择真实 Provider 意味着演示文稿中的待译文本会发送给第三方服务。只使用无敏感信息的材料，并遵守相应 Provider 的数据处理条款。

## 3. 五分钟演示脚本

### 0:00–0:40：一句话定位

> 这是一个状态化 PPT 翻译 Agent。模型只负责语义生成，任务状态、结构校验、失败修复、OOXML 写回和产物发布都由确定性程序控制。

说明这是匿名化作品集 Demo，公开页面只保留 PPT 翻译。

### 0:40–1:30：提交任务

1. 上传一份你有权使用、且已清除作者、批注、隐藏页和文档属性的 PPTX（仓库不附带客户或公司样例）。
2. 选择源语言和目标语言。
3. 选择仅译文或双语模式，并展示选页能力。
4. 选择已经配置好的 Provider。
5. 启动翻译。

不要在现场第一次测试大文件、扫描型演示文稿或复杂 SmartArt。

### 1:30–2:30：解释 Agent 工作流

围绕界面中的任务状态解释：

```text
解析 → 稳定翻译单元 → 结构化生成 → 质量门 → 定向修复 → 写回 → 原子发布
```

重点讲清楚：

- Provider 返回的是不可信输入，必须经过版本化协议校验。
- 单元和分段有稳定 ID，避免模型改变数量、顺序或写错位置。
- 只修复失败单元一次；仍失败就关闭任务，不发布部分成功的文件。
- 长任务落在数据库账本中，不依赖浏览器请求一直存活。

### 2:30–3:30：展示结果

下载译文并打开，选择两页对比：

- 一页普通标题与正文，展示结构和基本样式保留。
- 一页包含多个文本框或双语内容，诚实说明小文本框可能需要人工复核。

### 3:30–4:30：讲可靠性

用三个故障问题收束：

- **Worker 中断**：lease、版本号和状态投影让任务可以被识别和恢复。
- **模型输出不合法**：结构/语义质量门加一次定向修复，之后失败关闭。
- **重复执行**：不可变源文件、独立 attempt、哈希校验和原子晋升避免污染已发布产物。

### 4:30–5:00：讲指标边界

可以说：

> 在 100 个完全相同单元的确定性夹具中，翻译记忆把 Provider 调用从 100 次降到 1 次，并保持输出哈希和顺序一致。

紧接着说明这不是“线上成本降低 99%”的证明。真实收益取决于内容重复率、模型、网络和缓存命中率。

## 4. 面试官常见追问

### 为什么这是 Agent，不只是 API 封装？

因为它有持久化任务状态、上下文与可选记忆、固定工具链、输出反馈校验、失败修复循环和最终文件动作。准确说法是“有界 Agentic Workflow”，不是能自由规划任意工具的通用 Agent。

### 为什么不用 ReAct 或 LangGraph？

这个问题的步骤稳定，核心风险是长任务一致性和文件副作用，不是开放式规划。显式状态机和数据库任务账本更容易校验、恢复和审计；未来只有出现真实的动态决策需求时才值得引入通用图编排。

### 如何处理幻觉？

不能声称消除所有幻觉。系统能机械验证 JSON 结构、ID、顺序、数量、保留标记、精确术语和高置信源语言残留；自然度和事实语义仍需要真实评测集或人工复核。

### 版式能否 100% 保留？

不能保证。OOXML 精确写回与可编辑 AutoFit 策略能降低破坏，但翻译后的字符长度、组合图形、SmartArt、字体替换和极小文本框仍可能产生溢出或重叠。

### 为什么使用数据库，而不是只放在内存队列？

浏览器请求和进程生命周期都短于大型 PPT 翻译。数据库账本提供任务所有权、版本、lease、取消和恢复所需的持久事实，Worker 只是执行者。作品集模式用零配置 SQLite 降低启动门槛，常规部署用 MySQL 承载并发与长期状态。

## 5. 指标真实性清单

演示或简历中可以使用：

- “确定性重复文本夹具中，100 个相同单元的调用数从 100 降到 1，输出哈希与顺序一致。”
- “本地无网络夹具中，V2 编排 p95 约 9.09 ms，旧路径约 32.75 ms。”
- “一个 35 页场景能够由 PowerPoint 原生打开并导出；5 个受影响页中 4 页视觉检查通过，1 页小型组合图例存在重叠。”

除非补充真实评测，否则不要声称：

- 生产成本降低固定百分比。
- 真实模型翻译准确率达到某个数字。
- 已经解决所有幻觉或术语错误。
- 任意 PPT 的版式都能 100% 保持。
- 已经具备自主 Planning、ReAct、多 Agent、RAG、向量记忆或模型微调。

## 6. 录屏与公开前检查

- 页面只出现 **PPT Agent Studio**，没有原公司 Logo、商标、域名或法律实体名。
- 浏览器书签、下载栏、通知、系统用户名和绝对路径不进入画面。
- 现场使用的演示文件名、作者、批注、隐藏页和文档属性均已脱敏。
- `.env`、终端历史和日志不包含 API Key、数据库密码、内网地址或真实账号。
- 预先验证 Provider 余额、网络、Demo SQLite、LibreOffice 和下载目录；只有展示常规部署时才需额外验证 MySQL。
- 准备一份已生成的匿名结果文件，应对现场网络或 Provider 故障；需要明确说明它是预生成备份。
- 发布仓库前另做许可证、提交历史、样例资产和生成物审查。UI 脱敏不等于完成公开发布合规审计。

## 7. 常见故障

### 数据库连接失败

核对 `DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`，并确认 MySQL 已创建数据库且账号拥有该库权限。

### Provider 立即失败

核对 Key、Base URL、模型名、余额和网络。不要把完整 Key 贴入错误报告或截图。

### 旧 `.ppt` 无法处理或渲染失败

确认 LibreOffice 已安装。Windows 的 `LIBREOFFICE_PATH` 应指向安装根目录，而不是 `soffice.exe` 文件本身。

### PPT 可以下载但局部拥挤

先用较短译文或仅译文模式复核。组合图形、极小文本框和字体缺失是重点人工检查区域；不要把可打开性等同于视觉完全通过。
