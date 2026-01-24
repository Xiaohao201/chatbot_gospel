# MediaCrawler

> 一个功能完善的社交媒体爬虫项目，支持多平台数据采集和聊天自动化

## 许可证声明

本项目采用 **NON-COMMERCIAL LEARNING LICENSE 1.1**（非商业学习许可证）。使用本代码即表示您同意：

1. 不得用于任何商业用途
2. 使用时应遵守目标平台的使用条款和 robots.txt 规则
3. 不得进行大规模爬取或对平台造成运营干扰
4. 应合理控制请求频率，避免给目标平台带来不必要的负担
5. 不得用于任何非法或不当的用途

详细许可条款请参阅项目根目录下的 LICENSE 文件。

---

## 特性

### 支持平台

| 平台 | 代码标识 | 支持功能 |
|------|----------|----------|
| 小红书 | `xhs` | 笔记搜索、详情、创作者主页 |
| 抖音 | `dy` | 视频搜索、详情、创作者主页 |
| 快手 | `ks` | 视频内容爬取 |
| B站 | `bili` | 视频搜索、详情、评论数据 |
| 微博 | `wb` | 内容爬取 |
| 贴吧 | `tieba` | 贴子数据 |
| 知乎 | `zhihu` | 问题、文章、回答数据 |

### 核心功能

- **多种爬取类型**: 关键词搜索、帖子详情、创作者主页
- **灵活登录方式**: 二维码登录、手机号登录、Cookie 登录
- **反检测机制**:
  - 支持无头浏览器模式
  - 支持 CDP 模式（连接本地 Chrome/Edge）
  - IP 代理池支持
- **数据导出**: JSON、Excel、数据库存储
- **聊天自动化**: 支持多平台私信自动回复（B站、抖音、知乎）
- **数据处理**: 词云生成、数据可视化、中文分词

---

## 环境要求

- Python 3.11+
- Windows / macOS / Linux
- MySQL / SQLite / MongoDB / Redis（可选）

---

## 快速开始

### 1. 安装依赖

使用 uv（推荐）：

```bash
pip install uv
uv sync
```

或使用 pip：

```bash
pip install -r requirements.txt
```

### 2. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env` 并根据需要修改：

```bash
cp .env.example .env
```

主要配置项：

```env
# 爬取平台 (xhs/dy/ks/bili/wb/tieba/zhihu)
PLATFORM=xhs

# 爬取类型 (search/detail/creator)
CRAWLER_TYPE=search

# 关键词搜索
KEYWORDS=Python,编程

# 数据存储方式 (json/db/excel/sqlite)
SAVE_DATA_OPTION=json

# 是否启用词云生成
ENABLE_GET_WORDCLOUD=false
```

### 4. 运行爬虫

```bash
python main.py
```

---

## 命令行参数

```bash
# 初始化数据库
python main.py --init-db

# 指定平台
python main.py --platform xhs

# 指定爬取类型
python main.py --crawler-type search
```

---

## 项目结构

```
chatbot_gospel/
├── main.py                 # 主程序入口
├── pyproject.toml         # 项目配置
├── requirements.txt        # Python 依赖
├── media_platform/        # 媒体平台爬虫
│   ├── bilibili/          # B站爬虫
│   ├── douyin/            # 抖音爬虫
│   ├── xhs/               # 小红书爬虫
│   ├── zhihu/             # 知乎爬虫
│   ├── kuaishou/          # 快手爬虫
│   ├── weibo/             # 微博爬虫
│   └── tieba/             # 贴吧爬虫
├── chat/                  # 聊天自动化模块
│   ├── bilibili_chat.py
│   ├── douyin_chat.py
│   └── zhihu_chat.py
├── database/              # 数据库模型和连接
├── base/                  # 基础爬虫类
├── config/                # 配置文件
├── api/                   # FastAPI Web API
├── tools/                 # 工具模块
├── store/                 # 数据存储模块
└── test/                  # 测试目录
```

---

## 技术栈

| 分类 | 技术 |
|------|------|
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 |
| **异步** | asyncio, aiofiles, httpx |
| **数据库** | MySQL, SQLite, MongoDB, Redis |
| **浏览器** | Playwright |
| **数据处理** | Pandas, Matplotlib, WordCloud, jieba |
| **测试** | pytest, pytest-asyncio |

---

## 使用示例

### 爬取小红书笔记

```python
# .env 配置
PLATFORM=xhs
CRAWLER_TYPE=search
KEYWORDS=人工智能
SAVE_DATA_OPTION=json
```

### 爬取抖音视频

```python
# .env 配置
PLATFORM=dy
CRAWLER_TYPE=detail
KEYWORDS=https://www.douyin.com/video/xxxxx
```

### 启用私信自动化

```python
# .env 配置
PLATFORM=bili
SAVE_DATA_OPTION=db
ENABLE_CHAT_AUTOMATION=true
```

---

## 注意事项

1. **请求频率**: 请合理控制爬取频率，避免对目标平台造成压力
2. **账号安全**: 建议使用测试账号，避免主账号被封禁
3. **数据使用**: 爬取的数据仅供学习研究使用
4. **法律合规**: 遵守当地法律法规和平台服务条款

---

## 常见问题

**Q: 如何启用 CDP 模式？**

A: 在 `.env` 中设置 `CDP_ENABLED=true`，确保本地 Chrome/Edge 浏览器已启动。

**Q: 如何配置代理？**

A: 在 `.env` 中设置 `PROXY=http://127.0.0.1:7890`

**Q: 数据存储在哪里？**

A: 根据 `SAVE_DATA_OPTION` 配置：
- `json`: 存储在 `data/` 目录
- `excel`: 存储在 `data/` 目录
- `db/sqlite`: 存储在配置的数据库中

---

## 贡献

欢迎提交 Issue 和 Pull Request。

---

## 作者

程序员阿江-Relakkes <relakkes@gmail.com>

---

## 许可证

NON-COMMERCIAL LEARNING LICENSE 1.1

---

## 相关资源

- 原始仓库: https://github.com/NanmiCoder/MediaCrawler
