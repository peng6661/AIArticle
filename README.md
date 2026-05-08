# AIArticle - AI 视频转文章自动化流水线

> 视频下载 → 音频提取 → 语音转写 → AI 生成文章 → AI 配图 → 微信公众号草稿，一站式自动化。

## 功能特性

- **多平台视频下载**：支持抖音、B站、TikTok、Instagram、快手、X (Twitter)、YouTube 共 7 个平台
- **多平台视频搜索**：并发搜索多个平台，输入关键词快速找到目标视频
- **本地上传**：支持直接上传本地视频文件
- **AI 文章生成**：双 AI 服务商（SiliconFlow / 智谱 GLM），基于视频语音内容自动转为结构化文章
- **AI 配图**：根据文章内容自动生成插图，并发上传至微信素材库
- **RAG 知识库**：可导入文本/PDF/历史文章作为上下文，提升文章生成质量
- **热搜聚合**：实时聚合微博、抖音、B站、百度、知乎、微信、GitHub、掘金、牛客 9 大平台热搜
- **微信公众号发布**：自动清洗 HTML 并发布为微信草稿，支持预览链接
- **任务管理**：任务状态持久化（MySQL），支持暂停/恢复/取消/删除，服务重启后任务历史可查
- **流式下载**：后端代理流式传输，前端可显示真实下载进度

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy / MySQL |
| 前端 | Next.js 14 / React 18 / TypeScript / Tailwind CSS |
| AI 文本 | SiliconFlow API / 智谱 GLM（双服务商路由） |
| AI 图片 | SiliconFlow 图片生成 API |
| 语音转写 | faster-whisper（本地，支持 CUDA 加速） |
| 视频下载 | yt-dlp + 自研解析（多平台统一入口） |
| 文档格式 | Markdown 文章生成，自动转微信 HTML |
| 知识库 | ChromaDB 向量存储 + MySQL 元数据（RAG 检索增强） |
| 微信 | 微信公众平台 API（草稿发布 + 素材管理） |

## 处理流水线

```
Step 1: 下载视频/图片（多平台解析 + 下载）
    ↓
Step 2: 提取音频（FFmpeg）
    ↓
Step 3: 语音转写（faster-whisper）
    ↓
Step 4: AI 生成文章（SiliconFlow / 智谱 GLM → Markdown）
    ↓
Step 5: 并发生成配图 + 上传微信素材库
    ↓
Step 6: HTML 清洗（替换占位符为微信图片 URL）
    ↓
Step 7: 发布微信草稿（返回预览链接）
```

## 支持平台

| 平台 | 下载方式 | 备注 |
|------|---------|------|
| 抖音 | 自研解析 | 支持无水印视频 + 图文 |
| B站 (Bilibili) | 标准 HTTP | 视频流下载 |
| TikTok | 标准 HTTP | 国际版抖音 |
| Instagram | 自研解析 | 支持轮播图多图下载 |
| 快手 | 标准 HTTP | 视频下载 |
| X (Twitter) | CDN 直链优先，回退自研 | 非 yt-dlp 方案 |
| YouTube | yt-dlp | 流式传输 + JS Runtime PO Token |

## 项目结构

```
AIArticle/
├── backed/                          # 后端 (FastAPI)
│   ├── main.py                      # 应用入口
│   ├── config.yaml                  # 配置文件（从 config.yaml.example 复制）
│   ├── config.yaml.example          # 配置模板
│   ├── requirements.txt              # Python 依赖
│   ├── app/
│   │   ├── api/
│   │   │   ├── pipeline_router.py       # 流水线 API（单步/一键/暂停/恢复）
│   │   │   ├── full_pipeline_router.py  # 一键全流程
│   │   │   ├── video_router.py          # 视频解析/下载/流式传输
│   │   │   ├── hot_router.py            # 热搜聚合 API
│   │   │   ├── knowledge_router.py      # RAG 知识库 CRUD
│   │   │   ├── search_router.py         # 多平台视频搜索
│   │   │   └── _pipeline_utils.py       # 平台识别 + 通用下载辅助函数
│   │   ├── core/
│   │   │   ├── config.py                # 配置加载（YAML + 环境变量）
│   │   │   └── pipeline.py              # 流水线状态管理 + 任务持久化
│   │   ├── db/
│   │   │   ├── database.py               # 数据库连接池
│   │   │   └── models.py                 # SQLAlchemy ORM 模型
│   │   ├── schemas/
│   │   │   └── pipeline.py               # Pydantic 请求/响应模型
│   │   └── services/
│   │       ├── youtube_download_service.py  # YouTube 专用下载（yt-dlp）
│   │       ├── video_parser.py              # 平台自动识别路由
│   │       ├── video_search_service.py      # 多平台视频搜索
│   │       ├── hot_service.py               # 热搜聚合（9 平台）
│   │       ├── audio_service.py             # FFmpeg 音频提取
│   │       ├── transcribe_service.py        # Whisper 语音转写
│   │       ├── article_service.py           # AI 文章生成（Function Calling）
│   │       ├── image_service.py             # AI 配图 + 微信素材上传
│   │       ├── html_service.py              # 微信 HTML 清洗
│   │       ├── wechat_service.py            # 微信草稿发布
│   │       └── rag/                          # RAG 知识库子模块
│   │           ├── chunker/                  # 文档分块
│   │           ├── document_parser/          # 文本/PDF 解析
│   │           ├── embedding_service/        # 嵌入服务
│   │           ├── rag_service/              # RAG 检索
│   │           └── vector_store/             # ChromaDB 向量存储
│   └── ...
├── frontend/                        # 前端 (Next.js)
│   ├── app/
│   │   ├── page.tsx                 # 主页面（任务创建 + 管理）
│   │   ├── download/page.tsx         # 下载模式（解析/流式下载/搜索）
│   │   └── knowledge/page.tsx       # 知识库管理页面
│   ├── components/
│   │   ├── navbar.tsx               # 导航栏
│   │   └── hot-search-shelf.tsx     # 热搜聚合展示组件
│   ├── lib/
│   │   ├── tasks-api.ts            # 后端任务 API 封装
│   │   └── task-settings.ts        # localStorage 配置管理
│   └── types/
│       └── task.ts                  # TypeScript 类型定义
├── DESIGN.md                        # 设计规范文档
└── README.md
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- MySQL 8.0+
- FFmpeg（音频提取需要，imageio-ffmpeg 会自动安装）
- CUDA（可选，加速语音转写）
- Node.js（YouTube 下载 PO Token 生成需要）

### 1. 克隆项目

```bash
git clone https://github.com/peng6661/AIArticle.git
cd AIArticle
```

### 2. 后端配置

```bash
cd backed

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填写真实值
copy config.yaml.example config.yaml
```

编辑 `backed/config.yaml`，填写必要配置：

```yaml
siliconflow:
  api_key: "your-siliconflow-api-key"    # SiliconFlow API Key

zhipu:
  api_key: "your-zhipu-api-key"           # 智谱 GLM API Key（可选，备用）

wechat:
  appid: "your-wechat-appid"
  appsecret: "your-wechat-appsecret"
  default_author: "AIcreator"             # 默认文章作者
  declare_original: true                 # 默认声明原创

database:
  url: "mysql+pymysql://user:password@127.0.0.1:3306/aicreator?charset=utf8mb4"

# YouTube 配置（重要：新版 yt-dlp 必须）
youtube:
  cookies_source: "file"                 # 从 cookies 文件读取（推荐）
  cookies_file: "cookies_youtube.txt"     # Netscape 格式 cookies 文件
  js_runtime: "auto"                      # 自动检测 node/deno/bun（生成 PO Token）
  remote_components: "github"             # 启用远程组件（JS 挑战求解，必须）
```

初始化数据库：

```bash
python -c "from app.db.database import init_db; import asyncio; asyncio.run(init_db())"
```

启动后端：

```bash
python main.py
# 服务运行在 http://localhost:8000
# API 文档：http://localhost:8000/docs
```

### 3. YouTube Cookies 导出说明

YouTube 需要登录验证才能下载视频。步骤：

1. 在 Chrome/Edge 安装扩展 **[Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookies-txt-locally/)**
2. 打开 **https://www.youtube.com**（确保已登录你的 Google 账号）
3. 点击扩展图标 → **Export** → 选 `youtube.com` → 下载
4. 将下载的文件保存为 `backed/cookies_youtube.txt`

> Cookies 会随时间失效，失效后重新导出一次即可。

### 4. 前端配置

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 前端运行在 http://localhost:3000
```

前端通过 Next.js API Routes 代理后端请求，无需额外配置跨域。

## API 概览

### 流水线 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/pipeline/run` | 一键全流程（URL 或本地上传） |
| `POST` | `/pipeline/step/download` | Step1: 下载视频 |
| `POST` | `/pipeline/step/extract_audio` | Step2: 提取音频 |
| `POST` | `/pipeline/step/transcribe` | Step3: 语音转写 |
| `POST` | `/pipeline/step/generate_article` | Step4: AI 生成文章 |
| `POST` | `/pipeline/step/generate_image` | Step5: 生成配图 |
| `POST` | `/pipeline/step/convert_html` | Step6: HTML 清洗 |
| `POST` | `/pipeline/step/publish_draft` | Step7: 发布微信草稿 |
| `GET` | `/pipeline/jobs/{job_id}` | 查询任务进度 |
| `GET` | `/pipeline/jobs` | 获取所有任务列表 |
| `POST` | `/pipeline/jobs/{job_id}/pause` | 暂停任务 |
| `POST` | `/pipeline/jobs/{job_id}/resume` | 恢复任务 |
| `POST` | `/pipeline/jobs/{job_id}/cancel` | 取消任务 |
| `DELETE` | `/pipeline/jobs/{job_id}` | 删除任务 |

### 视频 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/video/parse` | 解析链接（自动识别平台） |
| `GET` | `/api/video/download` | 流式下载视频/图片 |
| `GET` | `/api/video/platforms` | 获取支持平台列表 |
| `POST` | `/api/video/search` | 多平台视频搜索 |
| `GET` | `/api/serve-file` | 服务本地文件（图片/视频） |

### 热搜 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/hot/{platform}` | 获取指定平台热搜（9 平台） |
| `GET` | `/hot/all` | 获取全部平台热搜 |

### 知识库 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/knowledge/collections` | 获取知识库集合列表 |
| `POST` | `/knowledge/collections` | 创建知识库集合 |
| `DELETE` | `/knowledge/collections/{id}` | 删除知识库集合 |
| `POST` | `/knowledge/documents` | 上传文档（文本/PDF/历史文章） |
| `GET` | `/knowledge/documents` | 获取集合内文档列表 |
| `DELETE` | `/knowledge/documents/{id}` | 删除文档 |
| `POST` | `/knowledge/search` | RAG 检索测试 |

## 环境变量

以下敏感配置支持通过环境变量设置：

| 环境变量 | 说明 |
|---------|------|
| `SILICONFLOW_API_KEY` | SiliconFlow API Key |
| `ZHIPU_API_KEY` | 智谱 GLM API Key |
| `WECHAT_APPID` | 微信公众号 AppID |
| `WECHAT_APPSECRET` | 微信公众号 AppSecret |
| `DATABASE_URL` | MySQL 连接 URL |
| `MYSQL_PASSWORD` | MySQL 密码 |
| `TRANSCRIBE_DEVICE` | 转写设备（auto/cpu/cuda） |

## License

MIT
