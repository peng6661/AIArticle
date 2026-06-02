# AIArticle

> 把视频、图文或文案素材转成微信公众号草稿的自动化流水线。

AIArticle 是一个本地运行的内容生产工具。它负责下载素材、提取音频、语音转写、生成 Markdown 文章、生成封面图、清洗微信 HTML，并最终发布到微信公众号草稿箱。

当前主页流程以“发布微信草稿”为终点。也就是说，正常生成任务需要提供微信公众号 AppID / AppSecret，项目不再把“只生成不发布”作为主页主流程。

## 核心能力

- **全流程生成**：分享链接 → 下载 → 音频 → 转写 → AI 写作 → 封面图 → 微信草稿。
- **多平台下载**：支持抖音、Instagram、B 站、TikTok、快手、X(Twitter)、YouTube。
- **本地素材入口**：支持上传本地视频，或上传 txt / md / pdf 文案，跳过前置步骤直接进入文章生成。
- **文章生成**：通过 Function Calling 输出结构化结果，正文为 Markdown，标题和正文分离。
- **写作风格约束**：偏技术博主口语风格，不强制大标题和固定小节数量；如果原始文案包含操作步骤，会展开到具体实操。
- **AI 封面图**：支持 SiliconFlow / 智谱图片模型配置，封面图生成后进入微信素材流程。
- **RAG 知识库**：支持文本、Markdown、PDF、历史任务文章入库，使用 ChromaDB 向量库 + MySQL 元数据。
- **向量清理**：删除知识库文档时，会按导入时保存的 `vector_doc_id` 清理对应向量分块。
- **热搜聚合**：聚合微博、抖音、B 站、百度、知乎、微信、GitHub、掘金、牛客、AI HOT 日报、AI HOT 精选。
- **视频搜索**：当前注册 B 站和 YouTube 搜索入口，按关键词并发搜索。
- **任务管理**：任务持久化到 MySQL，支持暂停、恢复、重试、再次生成、删除、批量删除。
- **隐私隔离**：真实配置、cookies、环境变量、缓存、下载产物都通过 `.gitignore` 排除。

## 最新维护

- **一键启动脚本**：项目根目录 `start.bat` 双击即可同时启动前后端，后端就绪后再启动前端，避免代理报错。双击 Ctrl+C（3 秒内）停止所有服务，三层清理确保端口释放。
- **资源库页面**（`/resources`）：无限滚动加载、骨架屏、回到顶部按钮，后端聚合爬虫提供数据源。
- **热搜面板优化**：拖拽才能触发展开，纯点击不触发；fetch 加 3 次重试 + 递增间隔，应对后端临时不可用。
- **启动脚本 Windows 兼容**：`shell=True` 解析 npm.cmd、`PYTHONUTF8=1` 防止中文路径乱码、`CREATE_NO_WINDOW` 不弹额外窗口。
- RAG 检索配置现在会完整贯穿全流程、上传后继续、失败重试和再次生成，前端设置的 `rag_top_k` 会保存到 `content_tasks.rag_top_k` 并在检索时生效。
- 本地文件预览与视频信息接口改用路径归属判断，避免同前缀目录被误判为允许访问目录。
- 微信 HTML 转换步骤统一从 Markdown 正文字段读取内容，避免后续把已生成 HTML 再当 Markdown 二次转换。
- 跳过封面图时，任务恢复和完成判断会按实际启用的步骤计算，不再把封面生成步骤当成必选步骤。
- 前端任务 API 类型补齐了 RAG 与跳过封面图相关字段，减少设置静默丢失。

## 技术栈

| 模块 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy / MySQL |
| 前端 | Next.js 14 / React 18 / TypeScript / Tailwind CSS |
| AI 文本 | SiliconFlow / 智谱，OpenAI 兼容接口 |
| AI 图片 | SiliconFlow / 智谱图片生成接口 |
| 语音转写 | faster-whisper，本地转写，支持 CPU / CUDA |
| 音频处理 | FFmpeg，依赖 `imageio-ffmpeg` 兜底 |
| 视频下载 | yt-dlp + 多平台自研解析 |
| 知识库 | ChromaDB + MySQL + embedding 缓存 |
| 文档解析 | 文本 / Markdown / PDF |
| 发布 | 微信公众号素材与草稿 API |

## 流程

```text
Step 1  下载视频或图片
Step 2  提取音频
Step 3  语音转写
Step 4  AI 生成 Markdown 文章
Step 5  生成封面图
Step 6  转换并清洗微信 HTML
Step 7  发布微信公众号草稿
```

如果从本地视频开始，会跳过 Step 1。

如果从文案文件开始，会跳过 Step 1-3，直接进入 Step 4。

## 支持平台

| 平台 | 能力 |
|---|---|
| 抖音 | 分享文本解析，视频 / 图文下载 |
| Instagram | Reels / 视频 / 轮播图片下载 |
| B 站 | 视频解析与下载 |
| TikTok | 视频解析与下载 |
| 快手 | 视频解析与下载 |
| X(Twitter) | 视频 / 图片解析，直链优先，必要时回退 |
| YouTube | yt-dlp 下载，支持 cookies、JS runtime、remote components |

## 页面

| 页面 | 路径 | 说明 |
|---|---|---|
| 主页 | `/` | 创建全流程任务，查看历史任务，重试、暂停、再次生成 |
| 下载页 | `/download` | 解析链接、搜索视频、下载视频/图片，显示真实进度 |
| 知识库 | `/knowledge` | 创建集合、上传文档、从历史任务导入、检索测试、删除文档 |
| 资料库 | `/resources` | 资源资料库，无限滚动浏览，支持搜索筛选 |

## 项目结构

```text
AIArticle/
├── start.bat                  # 一键启动入口（Windows）
├── start_all.py               # 一键启动脚本（前端 + 后端）
├── backed/
│   ├── main.py
│   ├── init_db.py
│   ├── start.bat              # 单独启动后端
│   ├── start_server.py        # 后端守护启动脚本
│   ├── config.yaml.example
│   ├── requirements.txt
│   └── app/
│       ├── api/
│       │   ├── full_pipeline_router.py
│       │   ├── pipeline_router.py
│       │   ├── video_router.py
│       │   ├── search_router.py
│       │   ├── hot_router.py
│       │   ├── knowledge_router.py
│       │   └── resource_library_router.py
│       ├── core/
│       │   ├── config.py
│       │   └── pipeline.py
│       ├── db/
│       │   ├── database.py
│       │   └── models.py
│       ├── schemas/
│       │   └── pipeline.py
│       └── services/
│           ├── article_service.py
│           ├── audio_service.py
│           ├── transcribe_service.py
│           ├── image_service.py
│           ├── html_service.py
│           ├── wechat_service.py
│           ├── *_download_service.py
│           ├── video_search_service.py
│           ├── hot_service.py
│           └── rag/
│               ├── chunker.py
│               ├── document_parser.py
│               ├── embedding_cache.py
│               ├── embedding_service.py
│               ├── rag_service.py
│               └── vector_store.py
├── frontend/
│   ├── start.bat              # 单独启动前端
│   ├── start_server.py        # 前端守护启动脚本
│   ├── app/
│   │   ├── page.tsx
│   │   ├── download/page.tsx
│   │   ├── knowledge/page.tsx
│   │   └── resources/page.tsx
│   ├── components/
│   │   ├── navbar.tsx
│   │   ├── hot-search-shelf.tsx
│   │   └── video-background.tsx
│   ├── lib/
│   │   ├── api-client.ts
│   │   ├── tasks-api.ts
│   │   └── task-settings.ts
│   └── types/task.ts
└── README.md
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8.0+
- FFmpeg
- Chrome / Edge，可选，用于导出 YouTube cookies
- CUDA，可选，用于加速 faster-whisper

### 一键启动（Windows）

项目根目录双击 `start.bat`，自动启动后端和前端，浏览器自动打开。双击 Ctrl+C（3 秒内）停止所有服务。

### 后端

```bash
git clone https://github.com/peng6661/AIArticle.git
cd AIArticle/backed

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
copy config.yaml.example config.yaml
```

Linux / macOS 激活虚拟环境：

```bash
source .venv/bin/activate
```

编辑 `backed/config.yaml`。

```yaml
paths:
  downloads_dir: "downloads"
  outputs_dir: "outputs"

siliconflow:
  base_url: "https://api.siliconflow.cn/v1"
  default_text_model: "Qwen/Qwen3-14B"
  default_image_model: "Qwen/Qwen-Image"

zhipu:
  base_url: "https://open.bigmodel.cn/api/paas/v4"
  default_text_model: "glm-4-flash"
  default_image_model: "cogview-3"

wechat:
  appid: "YOUR_APPID"
  appsecret: "YOUR_APPSECRET"

database:
  url: "mysql+pymysql://user:password@127.0.0.1:3306/aicreator?charset=utf8mb4"

rag:
  embedding_model: "embedding-3"
  embedding_base_url: "https://open.bigmodel.cn/api/paas/v4"
  top_k: 5

youtube:
  cookies_source: "file"
  cookies_file: "cookies_youtube.txt"
  js_runtime: "auto"
  remote_components: "github"
```

AI 文本、图片和 RAG API Key 可以在前端表单里填写，也可以按接口请求体传入。后端配置主要放默认模型、数据库、微信和 YouTube 下载参数。

初始化数据库：

```bash
python init_db.py --create-db
```

启动后端：

```bash
python main.py
```

后端默认地址：

```text
http://localhost:8000
```

API 文档：

```text
http://localhost:8000/docs
```

### 前端

```bash
cd ../frontend
npm install
npm run dev
```

前端默认地址：

```text
http://localhost:3000
```

如果后端不在 `http://localhost:8000`，在前端环境变量里设置：

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## YouTube Cookies

部分 YouTube 视频需要登录态。

1. 在 Chrome / Edge 安装 `Get cookies.txt LOCALLY`。
2. 登录 `https://www.youtube.com`。
3. 导出 `youtube.com` 的 cookies。
4. 保存为 `backed/cookies_youtube.txt`。

`cookies_youtube.txt` 已被 `.gitignore` 排除，不要提交。

## API 概览

### Pipeline

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/pipeline/run` | 一键全流程 |
| `POST` | `/pipeline/upload-video` | 上传本地视频，从提取音频开始 |
| `POST` | `/pipeline/upload-text` | 上传 txt / md / pdf，从文章生成开始 |
| `GET` | `/pipeline/jobs` | 任务列表 |
| `GET` | `/pipeline/jobs/{job_id}` | 查询任务状态 |
| `DELETE` | `/pipeline/jobs/{job_id}` | 删除任务 |
| `POST` | `/pipeline/jobs/batch-delete` | 批量删除任务 |
| `POST` | `/pipeline/jobs/{job_id}/pause` | 暂停任务 |
| `POST` | `/pipeline/jobs/{job_id}/resume` | 恢复任务 |
| `POST` | `/pipeline/jobs/{job_id}/retry` | 重试最近失败步骤 |
| `POST` | `/pipeline/jobs/{job_id}/regenerate` | 复用文案再次生成 |
| `POST` | `/pipeline/step/download` | Step 1 下载 |
| `POST` | `/pipeline/step/extract_audio` | Step 2 提取音频 |
| `POST` | `/pipeline/step/transcribe` | Step 3 转写 |
| `POST` | `/pipeline/step/convert_html` | Step 6 HTML 清洗 |
| `POST` | `/pipeline/step/publish_draft` | Step 7 发布草稿 |

Step 4 文章生成和 Step 5 生图不再提供独立单步端点，统一由全流程、上传文案、再次生成、恢复任务等路径驱动。

### 视频与下载

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/video/parse` | 解析视频链接 |
| `GET` | `/api/video/parse` | GET 方式解析 |
| `GET` | `/api/video/platforms` | 下载支持平台 |
| `GET` | `/api/video/preview` | 图片预览代理 |
| `GET` | `/api/video/download` | 流式下载视频 / 图片 |
| `GET` | `/api/video/youtube-metadata` | YouTube 元数据与大小 |
| `POST` | `/api/video/youtube-cancel` | 取消 YouTube 下载 |
| `GET` | `/api/video/search/platforms` | 搜索支持平台 |
| `POST` | `/api/video/search` | 多平台视频搜索 |

### 热搜

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/hot/boards` | 获取聚合热榜，支持 `force_refresh=true` |

### 知识库

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/knowledge/collections` | 集合列表 |
| `POST` | `/api/knowledge/collections` | 创建集合 |
| `DELETE` | `/api/knowledge/collections/{collection_id}` | 删除集合 |
| `POST` | `/api/knowledge/documents/text` | 导入文本 / Markdown |
| `POST` | `/api/knowledge/documents/pdf` | 导入 PDF |
| `POST` | `/api/knowledge/documents/from-job` | 从历史任务导入 |
| `GET` | `/api/knowledge/documents` | 文档列表 |
| `DELETE` | `/api/knowledge/documents/{doc_id}` | 删除文档和对应向量分块 |
| `POST` | `/api/knowledge/search` | 检索测试 |

### 资料库

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/resource-library/resources` | 资源列表，支持分页、搜索、分类筛选 |

### 文件代理

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/serve-file` | 预览 / 下载本地 outputs、downloads 文件 |
| `GET` | `/api/video-info` | 查询本地视频文件大小 |
| `GET` | `/api/stream-video` | 远程视频流式代理 |

## 环境变量

| 变量 | 说明 |
|---|---|
| `NEXT_PUBLIC_API_URL` | 前端访问的后端地址 |
| `WECHAT_APPID` | 微信公众号 AppID |
| `WECHAT_APPSECRET` | 微信公众号 AppSecret |
| `DATABASE_URL` | MySQL 连接 URL |
| `MYSQL_PASSWORD` | MySQL 密码覆盖 |
| `TRANSCRIBE_DEVICE` | 转写设备，`auto` / `cpu` / `cuda` |
| `TRANSCRIBE_COMPUTE_TYPE` | faster-whisper 计算精度 |
| `RAG_EMBEDDING_API_KEY` | RAG 向量模型专用 API Key |

## 隐私与提交安全

不要提交以下文件：

- `backed/config.yaml`
- `backed/cookies_youtube.txt`
- `.env`、`.env.local`
- `backed/data/`
- `backed/downloads/`
- `backed/outputs/`
- `backed/.rag_cache/`
- `.venv/`
- `frontend/.next/`
- `frontend/node_modules/`

这些路径已经写入 `.gitignore`。真实 API Key、数据库密码、微信密钥、YouTube cookies 只放在本地配置或环境变量里。

## 常用命令

```bash
# 后端语法检查
python -m py_compile backed/main.py backed/app/services/article_service.py

# 前端类型检查
cd frontend
npx tsc --noEmit
```

## Recent Updates

- Added one-click startup scripts (`start.bat` + `start_all.py`) for Windows, with sequential backend-first launch and three-layer process cleanup.
- Added resources page (`/resources`) with infinite scroll, skeleton loading, and back-to-top button.
- Added resource library backend API (`resource_library_router.py`) with pagination and search.
- Improved hot-search shelf: drag threshold to prevent click triggering, fetch retry with exponential backoff.
- Fixed Windows startup script issues: `shell=True` for npm.cmd resolution, GBK encoding, port cleanup.
- Added article source mode support for video transcripts and uploaded text rewrites.
- Preserved article source mode across full runs, uploads, retries, resumes, and regeneration.
- Added RAG embedding model/provider/key persistence for resumed and regenerated article tasks.
- Improved article generation prompts for text rewrite workflows and added retry handling for empty LLM output.
- Fixed job status loading when pending steps have no `started_at` timestamp.
- Fixed Pydantic startup warning for the transcription `model_size` request field.
- Improved cover image publishing fallback when image generation is skipped or unavailable.

## License

MIT
