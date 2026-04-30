# AIArticle - AI 视频转文章自动化流水线

> 视频下载 → 音频提取 → 语音转写 → AI 生成文章 → AI 配图 → 微信公众号草稿，一站式自动化。

## 功能特性

- **多平台视频下载**：支持抖音、B站、TikTok、Instagram、快手、X (Twitter)、YouTube 共 7 个平台
- **本地上传**：支持直接上传本地视频文件
- **AI 文章生成**：基于 SiliconFlow API（兼容 OpenAI 接口），自动将视频内容转为结构化文章
- **AI 配图**：根据文章内容自动生成插图，并上传至微信素材库
- **微信公众号发布**：自动清洗 HTML 并发布为微信草稿，支持预览链接
- **任务管理**：任务状态持久化（MySQL），支持暂停/恢复/取消/删除，服务重启后任务历史可查
- **流式下载**：后端代理流式传输，前端可显示真实下载进度

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy / MySQL |
| 前端 | Next.js 14 / React 18 / TypeScript / Tailwind CSS |
| AI | SiliconFlow API（文本生成 + 图片生成） |
| 视频下载 | yt-dlp / 平台自研解析 |
| 语音转写 | faster-whisper（本地，支持 CUDA 加速） |
| 微信 | 微信公众平台 API（草稿发布 + 素材管理） |

## 处理流水线

```
Step 1: 下载视频/图片（多平台解析 + 下载）
    ↓
Step 2: 提取音频（FFmpeg）
    ↓
Step 3: 语音转写（faster-whisper）
    ↓
Step 4: AI 生成文章（SiliconFlow → 结构化 JSON：标题 + 正文 + 图片提示词）
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
| B站 (Bilibili) | yt-dlp | 视频流下载 |
| TikTok | yt-dlp | 国际版抖音 |
| Instagram | 自研解析 | 支持轮播图多图下载 |
| 快手 | yt-dlp | 视频下载 |
| X (Twitter) | 自研解析 | 非yt-dlp方案 |
| YouTube | yt-dlp | 流式传输 |

## 项目结构

```
AIArticle/
├── backed/                          # 后端 (FastAPI)
│   ├── main.py                      # 应用入口
│   ├── config.yaml.example          # 配置模板（复制为 config.yaml 使用）
│   ├── requirements.txt             # Python 依赖
│   ├── init_db.py                   # 数据库初始化
│   ├── app/
│   │   ├── api/
│   │   │   ├── pipeline_router.py   # 流水线 API（单步/一键/暂停/恢复）
│   │   │   ├── full_pipeline_router.py
│   │   │   └── video_router.py      # 视频解析/下载/平台列表 API
│   │   ├── core/
│   │   │   ├── config.py            # 配置加载（YAML + 环境变量）
│   │   │   └── pipeline.py          # 流水线状态管理 + 任务持久化
│   │   ├── db/
│   │   │   ├── database.py          # 数据库连接
│   │   │   └── models.py            # SQLAlchemy 模型
│   │   ├── schemas/
│   │   │   └── pipeline.py          # Pydantic 请求/响应模型
│   │   └── services/
│   │       ├── douyin_download_service.py
│   │       ├── bilibili_download_service.py
│   │       ├── tiktok_download_service.py
│   │       ├── instagram_download_service.py
│   │       ├── kuaishou_download_service.py
│   │       ├── x_download_service.py
│   │       ├── youtube_download_service.py
│   │       ├── video_parser.py      # 平台自动识别路由
│   │       ├── audio_service.py     # FFmpeg 音频提取
│   │       ├── transcribe_service.py # Whisper 语音转写
│   │       ├── article_service.py   # AI 文章生成
│   │       ├── image_service.py     # AI 配图 + 微信素材上传
│   │       ├── html_service.py      # 微信 HTML 清洗
│   │       └── wechat_service.py    # 微信草稿发布
│   └── ...
├── frontend/                        # 前端 (Next.js)
│   ├── app/
│   │   ├── page.tsx                 # 主页面（任务创建 + 管理）
│   │   ├── download/page.tsx        # 下载详情页
│   │   └── api/                     # Next.js API Routes
│   ├── components/
│   │   └── navbar.tsx               # 导航栏
│   ├── lib/
│   │   ├── api-client.ts            # 后端 API 客户端
│   │   ├── tasks-api.ts             # 任务管理 API
│   │   └── task-settings.ts         # 任务配置类型
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
- FFmpeg（音频提取需要）
- CUDA（可选，加速语音转写）

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

编辑 `backed/config.yaml`，填写以下必要配置：

```yaml
siliconflow:
  # 需要填入你的 SiliconFlow API Key（通过环境变量 SILICONFLOW_API_KEY 设置）
  base_url: "https://api.siliconflow.cn/v1"

wechat:
  appid: "你的微信AppID"
  appsecret: "你的微信AppSecret"

database:
  url: "mysql+pymysql://用户名:密码@127.0.0.1:3306/aicreator?charset=utf8mb4"
```

初始化数据库：

```bash
python init_db.py --create-db   # 自动创建数据库和表
```

启动后端：

```bash
python main.py
# 服务运行在 http://localhost:8000
# API 文档：http://localhost:8000/docs
```

### 3. 前端配置

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
| `POST` | `/pipeline/run` | 一键全流程（支持 URL 和本地上传） |
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

## 环境变量

以下敏感配置支持通过环境变量设置，避免明文写在 `config.yaml` 中：

| 环境变量 | 说明 |
|---------|------|
| `SILICONFLOW_API_KEY` | SiliconFlow API Key |
| `WECHAT_APPID` | 微信公众号 AppID |
| `WECHAT_APPSECRET` | 微信公众号 AppSecret |
| `DATABASE_URL` | MySQL 连接 URL |
| `MYSQL_PASSWORD` | MySQL 密码 |
| `TRANSCRIBE_DEVICE` | 转写设备（auto/cpu/cuda） |

## License

MIT
