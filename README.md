好的，根据你目前所有的规划、代码逻辑变更以及 Bug 排查记录，我为你拟写了这份 **README.md**。这份文件不仅包含了项目的目标和架构，还详细记录了本周的进度、关键逻辑的迭代（特别是针对用户系统和任务分发的调整）以及已解决的问题。
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-arena\Scripts\Activate.ps1
---
d:\Study\Programming\etrip\etrip心理\arena\.venv-arena\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010

# CommentRanking Demo

## 1. 项目简介
**CommentRanking Demo** 是一个专门用于收集人类对体育比赛解说（文本/音频）偏好的标注平台。通过“视频播放 + 多源解说对比 + 拖拽排序”的交互方式，系统能够收集高质量的 Ranking 数据，并最终导出为标准的数据集格式（JSONL/CSV），用于训练或评估多模态大模型在体育评论领域的表现。

## 2. 核心架构
- **前端**：采用“零构建”方案（原生 HTML5 + JS + CSS3），由后端直接托管。支持视频与多路音频同步播放、拖拽排序卡片、管理员消息中心。
- **后端**：基于 **FastAPI** 异步框架，使用 **SQLite** 存储用户、任务分配和标注结果。
- **存储**：本地静态资源目录（`data/matches/`）+ `manifest.json` 全局索引。
- **安全**：基于 HttpOnly Cookie 的 Session 认证，支持管理员（Admin）与普通用户（User）权限隔离。

---

## 3. 当前进度（本周：最小闭环 Demo）

### ✅ 基础功能实现
- **任务分发**：实现 `/api/tasks/next` 接口，支持“只文本/只音频/两者”模式，自动过滤当前用户已标注的任务。
- **交互标注**：实现“未排序池 + 已排序区”拖拽 UI，支持 Solo-Listen（音频互斥）和时间戳跳转功能。
- **数据导出**：支持管理员一键导出 `JSONL` 格式数据，包含完整的任务快照（Snapshot）以防 manifest 变更。
- **用户系统**：
  - 预置 6 名管理员（`wsq, hjn, sy, csk, mjz, xyc`），支持首次登录强制改密。
  - 普通用户注册审批流：`Register -> Pending -> Admin Approve/Reject`。

### ✅ 管理员管理端
- **统一侧边栏 (Sidebar)**：整合统计页、消息中心和退出登录。
- **消息中心 (Inbox)**：
  - **审批流**：管理员可处理新用户注册申请。
  - **广播动态**：实时展示管理员的操作审计日志（如：某管理员审批了某用户）。
- **统计分析**：支持查看单场比赛的标注详情及初步的 Ranking 统计（AvgRank）。

### 🛠 关键逻辑迭代与修复
1. **任务分发策略调整**：
   - 取消了复杂的“软锁（Assignment Lock）”机制。现在的逻辑是：**只要该用户未提交过某 Match 的 Judgment，即可领取。** 这种方式避免了并发锁导致的“新用户无任务可做”的问题，提升了分发效率。
2. **Bug 修复：新用户“显示全部标注完成”**：
   - **成因**：数据库中存在匿名测试阶段的垃圾数据，其 `user_id` 与新用户名碰撞；或前端 bfcache 恢复了旧的 DOM 状态。
   - **修复**：对 `/ui/` 所有资源强制执行 `no-store` 缓存策略；前端启动时强制重置（Reset）完成态浮层；后端清理非系统用户的脏数据。

---

## 4. 数据组织规范
```bash
arena/data/
├── manifest.json              # 数据全局索引
└── matches/                   # 比赛原始素材
    └── {match_id}/            # 唯一比赛 ID
        ├── video.mp4          # 视频文件
        └── commentary/        # 多源解说（.wav / .json）
```

### manifest.json 关键字段
- `matches[]`:
  - `match_id`: 唯一标识。
  - `commentaries[]`: `type` (text/audio/both), `path`, `source` 等。

---

## 5. 快速启动
1. **环境准备**：
   ```bash
   pip install fastapi uvicorn passlib[bcrypt] python-multipart
   ```
2. **启动服务**：
   ```bash
   python main.py
   ```
3. **访问路径**：
   - **入口**：`http://127.0.0.1:8010/` (自动跳转至 `/ui/login/`)
   - **管理员初始密码**：`123456` (登录后需修改)
   - **接口文档**：`/docs`

---

## 6. 待办事项 (Next Steps)
- [ ] **性能优化**：实现视频/音频的后台预取（Prefetch），减少用户切换任务时的等待。
- [ ] **数据质量**：在统计页增加“标注一致性”校验，自动标记 Ranking 差异极大的样本。
- [ ] **部署**：配置生产环境的环境变量（`SESSION_SECRET`），移除调试日志。

---

## 7. 本周更新（wk2）

- **解说数据改为“音文配对”组织。**  
  技术实现：`data/matches/{match_id}/commentary/cN/` 统一存放同一条解说的文本与音频，后端按 `text.path` 必填、`audio` 可空解析。

- **文本解说支持 `txt/json` 两种格式。**  
  技术实现：后端读取文本时先自动识别 JSON，再回退纯文本字符串，接口统一返回可渲染的 `text` 字段。

- **任务分发按资源可用性过滤，不再依赖旧 type 逻辑。**  
  技术实现：`mode=both/text` 返回有文本项，`mode=audio` 返回有音频项，并在任务接口补充 `has_audio`。

- **音视频联动播放更稳定。**  
  技术实现：点击解说音频后建立同一时间轴，拖动音频同步视频，音频结束后视频静音续播，并支持 `sync_offset_ms` 对齐扩展。

- **标注页交互空间优化。**  
  技术实现：顶部控制区精简，视频与列表间加入可拖拽分界线，动态调整视频高度并持久化到本地存储。

- **排序区支持跨列表拖拽与边缘自动滚动。**  
  技术实现：实现未排序/已排序双向拖拽、插入缝隙高亮、容器高亮，以及拖拽靠近边缘时 `requestAnimationFrame` 自动滚动。

- **已排序区支持紧凑视图。**  
  技术实现：默认紧凑模式仅显示标题+音频+单行摘要，点击摘要可展开详情，模式状态本地持久化。

- **导出预览空白问题已修复。**  
  技术实现：导出 JSONL 时将 `ranking` 中的 Pydantic 对象先转为字典后再序列化，避免流式导出异常。

---

## 8. 导出统计数据 JSONL 结构（易懂版）

每一行是一个完整的标注结果（一个 JSON 对象），常用字段如下：

- `judgment_id`：这条标注记录的唯一编号。  
- `match_id`：对应哪场比赛。  
- `labeler_id`：是哪位标注员提交的。  
- `created_at`：提交时间。  
- `mode`：标注模式（`audio` / `text` / `both`）。  
- `latency_ms`：本次操作耗时（毫秒，可为空）。  
- `reason`：人工备注（可为空）。  
- `flags`：附加信息（例如是否 `skipped`、浏览器信息等）。

- `ranking_ids`：解说 ID 的排序结果（从好到坏）。  
- `ranking`：对 `ranking_ids` 的可读化展开，每个元素包含：  
  - `rank`：名次  
  - `id`：解说 ID  
  - `source/language/type`：解说来源、语言、类型  
  - `text_snapshot`：文本摘要  
  - `audio_url_or_path`：音频地址或路径

- `match`：比赛快照信息，包含 `title/league/date/length_sec/video`，用于导出后仍可追溯当时任务上下文。

---

## 9. 贡献者
**Admin Team**: wsq, hjn, sy, csk, mjz, xyc

---

这份 README 覆盖了你从后端架构到前端交互，再到最近修复的“任务分发”和“缓存 Bug”的所有核心细节。直接保存为项目的 `README.md` 即可！

