## 色调更改
2026-04-13：全站视觉升级为浅色高级风。统一主色、背景渐变与卡片玻璃感，重设按钮/输入框/统计卡/完成弹层配色，移除深色底，提升信息对比与阅读舒适度，保持原有交互与布局不变。

## 数据重组与音文配对改造计划（新结构直改版）

### 1. 前提
- 当前数据集仅 2 个视频，且 `data/matches/*/commentary/c1,c2,c3...` 新结构已完成。
- 不做旧格式兼容，不保留历史 `type=text/audio/both` 分支。
- 只修改接口与组织逻辑，使系统完全按“音文配对”运行。

### 2. 数据与清单标准（唯一标准）
- 每条 commentary 对应一个目录：`commentary/cN/`。
- 目录内文件：
  - `text` 必填，支持 `txt/json`（如 `test1.txt` 或 `test2_streamerA_test.json`）；
  - `audio` 可空（如 `audio.wav` 可不存在）。
- `manifest.json` 规则：
  - 每个 commentary 统一视为“配对项”；
  - `text.path` 必填；
  - `text.format` 允许 `txt/json`（可省略，后端按内容自动识别）；
  - `audio.path` 可为空或缺省；
  - 保留并使用业务字段：`source`、`language`、`type`、`commentary_id` 等；
  - `commentary_id` 与目录一一对应（例如 `test1_c1` -> `commentary/c1/`）。

### 3. 后端修改步骤
- [app/manifest.py](D:\Study\Programming\etrip\etrip心理\arena\app\manifest.py)
  - 新规则校验：`text.path` 必有，`audio` 可空。
  - `text.format` 支持 `txt/json`，并允许省略。
- [app/main.py](D:\Study\Programming\etrip\etrip心理\arena\app\main.py)
  - `_filter_commentaries` 改为按资源可用性过滤：
    - `mode=both/text`：返回全部有文本项；
    - `mode=audio`：仅返回有音频项。
  - `get_next_task` 输出保持 `text + audio_url(可空)`，并补充 `has_audio`。
- [app/schemas.py](D:\Study\Programming\etrip\etrip心理\arena\app\schemas.py)
  - `CommentaryOut` 保留 `audio_url: str | None`，新增 `has_audio: bool` 方便前端渲染。

### 4. 前端修改步骤
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 卡片结构固定为：上方音频区、下方文本区。
  - `audio_url` 存在：点击音频区播放，再次点击切静音；保留单路激活。
  - `audio_url` 为空：显示“无音频”占位，仅渲染文本与时间戳跳转。
  - 去除依赖旧 `type` 的展示逻辑，改为按 `text/audio_url` 实际存在判断。
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 新增音频区样式（播放态/静音态/无音频态），统一卡片上下分区视觉。

### 5. 影响面联动
- 排序与提交接口不变：仍提交 `commentary_ids` 顺序。
- 统计与导出字段保持兼容；仅确保无音频项不会触发前端异常。
- 登录分流与消息中心不受本次改造影响。

### 6. 验收清单
- `mode=both`：返回并展示所有文本项，含无音频项。
- `mode=audio`：只出现有音频的 commentary。
- 文本兼容：`txt/json` 都能被 `/api/tasks/next` 正确内联返回。
- 标注页：每卡“上音频下文本”稳定显示；无音频卡无报错。
- 音频交互：点击播放，再点击静音可用；多卡不叠播。
- 两个视频数据都能完整跑通“领取任务 -> 排序提交 -> 下一条”。

## 音视频联动播放专项改造计划

### 1. 目标行为（按你最新要求）
- 页面进入后：自动播放视频且视频有声。
- 点击某条解说音频播放：立即建立该音频与视频的同一时间轴，默认从 0 秒同步起播。
- 用户拖动音频进度条：视频同步跳到同一时间点。
- 音频播放结束但视频未结束：继续播放视频，且视频静音（无声续播）。
- 同一时刻仅允许一条解说音频处于激活状态。

### 2. 后端改造步骤
- [app/schemas.py](D:\Study\Programming\etrip\etrip心理\arena\app\schemas.py)
  - 在 `CommentaryOut` 增加可选字段：`sync_offset_ms`（默认 `0`，用于未来非零对齐）。
  - 保留 `has_audio/audio_url`，供前端判断是否可绑定联动。
- [app/main.py](D:\Study\Programming\etrip\etrip心理\arena\app\main.py)
  - `get_next_task` 返回 `sync_offset_ms`（先统一返回 0）。
  - 若后续 `manifest` 提供逐条偏移，直接透传；不在前端写死。
- [data/manifest.json](D:\Study\Programming\etrip\etrip心理\arena\data\manifest.json)
  - 为每条 commentary 预留 `alignment.sync_offset_ms` 字段（可选），当前默认 0。

### 3. 前端改造步骤（核心）
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 状态新增：
    - `activeCommentaryId`
    - `syncMode`（`video_only`/`video_with_commentary`/`video_muted_tail`）
    - `activeSyncOffsetMs`
  - 初始化：
    - `loadFirstTask` 完成后自动 `video.play()`，`video.muted = false`。
  - 点击音频播放按钮：
    - 激活该 commentary；
    - `video.currentTime = 0`，`audio.currentTime = 0`（再叠加 offset）；
    - 同步 `play()`，并将视频静音（避免与解说叠音）。
  - 点击同一按钮第二次：
    - 仅切换该音频 `muted` 状态（不打断视频时钟）。
  - 音频 `seeking/seeked/timeupdate`：
    - 将 `video.currentTime` 同步到 `audio.currentTime + offset`。
  - 音频 `ended`：
    - 保持视频继续播放；
    - `video.muted = true`，进入 `video_muted_tail`。
  - 切换到其他 commentary：
    - 停止旧音频，重建新音频与视频同步关系。
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 增加联动状态样式（激活、静音、尾段续播提示）。

### 4. 事件冲突与边界处理
- 禁止“全局播放按钮”与“解说联动播放”互相抢状态：
  - 当有激活 commentary 时，全局按钮控制“视频+当前音频”联动。
- 浏览器自动播放限制：
  - 首次自动播放失败时给一次显式“点击开始播放”降级提示。
- 音频缺失项：
  - 不绑定联动逻辑，只允许视频原声播放与文本查看。

### 5. 专项验收
- 打开任务页后视频自动有声播放。
- 点击解说音频后，视频与该音频从头同步播放。
- 拖动音频进度，视频同步到同一时间。
- 音频结束后视频继续播放且静音。
- 切换不同 commentary 不出现多路音频同时播放。

## 解说框滚动与视频固定显示优化计划

### 1. 需求表述（优化后）
- 视频播放区在标注页中始终可见，不因页面滚动被挤出视窗。
- 用户滚轮/触控板滚动时，仅滚动鼠标当前所在的列表容器：
  - 鼠标位于“未排序”区域，只滚动未排序列表；
  - 鼠标位于“已排序”区域，只滚动已排序列表；
  - 其他区域不触发列表串联滚动。
- 禁止“滚到容器边界后把页面整体带着滚”的连带滚动。

### 2. 前端布局改造步骤
- [ui/index.html](D:\Study\Programming\etrip\etrip心理\arena\ui\index.html)
  - 保持现有结构，重点通过样式控制而非大改 DOM。
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 让视频区采用固定可见策略（建议 `position: sticky; top: ...`）。
  - 页面主容器设定明确高度（`100vh`）与分区滚动。
  - 为 `#unrankedList`、`#rankedList` 保持独立 `overflow: auto`，并加：
    - `overscroll-behavior: contain;`
    - `scrollbar-gutter: stable;`
  - 避免 `.main`、`.sortSection` 抢滚动焦点，确保只有列表自身滚动。

### 3. 前端交互逻辑改造步骤
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 新增滚动作用域控制：
    - 监听 `wheel` 事件，依据 `event.target.closest(...)` 判断所在列表；
    - 将滚动增量仅应用到命中的列表容器；
    - 对未命中列表区域的滚轮事件 `preventDefault`（按需，避免页面串滚）。
  - 新增触控板/触摸兼容策略：
    - 列表内自然滚动保留；
    - 边界处不向父层冒泡（结合 CSS `overscroll-behavior`）。
  - 不改变拖拽排序逻辑，仅修正滚动域行为。

### 4. 边界与冲突处理
- 拖拽过程中禁用列表滚轮劫持，避免排序与滚动冲突。
- 视频控件区域（播放条/音量条）滚轮不劫持，避免影响浏览器默认行为。
- 当列表内容不足一屏时，不应触发页面整体滚动抖动。

### 5. 验收清单
- 上下滚动时视频框始终可见。
- 鼠标在“未排序”列表上滚轮，仅未排序滚动。
- 鼠标在“已排序”列表上滚轮，仅已排序滚动。
- 列表到顶/到底时不再带动页面滚动。
- 拖拽排序、音视频播放、文本点击跳转功能无回归。

## 顶部控制区精简与视频高度可调计划

### 1. 需求重述（明确行为）
- 不再提供独立“播放/暂停”按钮，用户直接使用视频原生控件完成播放/暂停。
- 临时移除“音频跟随视频”开关，不在顶部占用空间。
- 支持用户动态调整视频展示框高度；视频高度变化后，下方“未排序/已排序”区域高度自动联动缩放，始终占满剩余可用空间。

### 2. 页面结构与样式改造
- [ui/index.html](D:\Study\Programming\etrip\etrip心理\arena\ui\index.html)
  - 精简 `topbar`：仅保留状态文本 `statusText`，移除 `globalPlayBtn` 与 `followVideoToggle` 节点。
  - 在视频区增加高度调节控件（建议横向 `range` 滑杆）：
    - `id="videoHeightRange"`
    - 建议范围：`28vh ~ 62vh`，步长 `1vh`。
  - 可选显示当前高度值标签：`id="videoHeightValue"`。
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 给视频容器添加 CSS 变量：`--video-h: 40vh`（默认值）。
  - `.video` 高度改为受变量控制（如 `height: var(--video-h)`），移除固定 `max-height` 约束。
  - `.sortSection` 保持 `flex:1; min-height:0; overflow:hidden;`，确保随视频高度自动收缩/扩展。
  - 调节条区域样式与浅色主题统一，保证移动端可触达。

### 3. 前端交互逻辑改造
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 删除与 `globalPlayBtn`、`followVideoToggle` 相关的 `qs`、事件绑定与播放分支逻辑。
  - 统一播放入口为视频原生控件与现有联动逻辑（点击解说音频时仍触发同步机制）。
  - 新增视频高度状态：
    - 本地存储键：`commentRanking.videoHeightVh`；
    - 初始化时读取并写入 CSS 变量；
    - 用户拖动 `videoHeightRange` 时实时更新变量与显示值。
  - 高度变化时无需手动改列表高度，依赖现有 flex 布局自动重排。

### 4. 兼容与边界处理
- 小屏（如高度 < 750px）时限制最大视频高度，避免列表可用空间过小（例如自动将上限压到 `52vh`）。
- 若本地存储值越界，回退默认 `40vh`。
- 保持“视频固定可见 + 列表独立滚动”策略不变，不破坏此前滚动域控制。

### 5. 验收清单
- 顶部不再显示“播放/暂停”按钮与“音频跟随视频”开关。
- 视频可通过原生控件正常播放/暂停，解说联动功能仍可用。
- 拖动视频高度滑杆后，视频高度实时变化，下方两个列表高度同步联动变化。
- 刷新页面后视频高度设置仍保留（本地存储生效）。
- 列表滚动作用域、拖拽排序、提交流程无回归。

## 排序框与未排序框拖拽增强计划

### 1. 需求重述（优化后）
- 保留当前按钮操作能力（加入排序、移出、上移、下移）不变。
- 在此基础上新增鼠标拖拽能力：
  - 从“未排序”拖入“已排序”（添加）；
  - 在“已排序”内拖动调整相对顺序（修改）；
  - 从“已排序”拖回“未排序”（移出）。
- 拖拽过程中提供清晰反馈：
  - 目标插入位置出现亮蓝色插入缝隙；
  - 可放置区域高亮；
  - 禁止放置时显示抑制态（不高亮）。

### 2. 交互规则定义
- 拖拽源：
  - 两个列表中的卡片均可拖拽；
  - 当前激活音频卡允许拖拽，但拖拽过程中不触发播放状态切换。
- 放置规则：
  - 拖到“已排序”容器空白区域：插入到末尾；
  - 拖到“已排序”某卡上方/下方：按光标位置计算插入索引；
  - 拖到“未排序”容器：从已排序移出并追加到未排序末尾；
  - 同一位置重复放置不触发状态变更。
- 回退规则：
  - 拖拽取消（ESC 或放置失败）后，列表恢复原状。

### 3. 前端实现步骤
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 状态扩展：
    - `draggingId`
    - `dragFrom`（`unranked|ranked`）
    - `dropZone`（当前目标列表）
    - `dropIndex`（目标插入索引）
  - 事件实现：
    - 卡片 `dragstart/dragend` 统一注册；
    - 列表容器 `dragenter/dragover/dragleave/drop` 统一处理；
    - 在 `dragover` 中按鼠标 Y 与卡片中线判断插入位置。
  - 数据更新：
    - 新增通用函数 `moveCommentary({id, from, to, index})`，同时维护 `st.unranked/st.ranked`。
    - 保持与现有按钮逻辑共存，按钮仍调用原更新逻辑或复用 `moveCommentary`。
  - 现有“仅 ranked 卡片可拖”的限制移除，改为双列表可拖。

### 4. 视觉反馈与样式
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 新增样式类：
    - `.list--drop-active`：容器高亮边框；
    - `.dropGap`：亮蓝色插入缝隙（2-3px，含轻微发光）；
    - `.card--dragging`：源卡片半透明；
    - `.list--drop-deny`：不可放置时低对比提示（可选）。
  - 反馈节奏：
    - `dragenter` 立即高亮容器；
    - `dragleave/drop` 清除高亮与插入缝隙。

### 5. 兼容与稳定性
- 与滚动作用域控制并存：拖拽期间保持 `state.isDragging=true`，避免滚轮劫持干扰。
- 与音视频联动并存：拖拽只改变排序，不改变当前音视频播放状态。
- 移动端暂不启用 HTML5 拖拽（后续如需再补 Pointer 方案）。

### 6. 验收清单
- 按钮功能仍全部可用（加入、移出、上移、下移）。
- 未排序 -> 已排序拖拽可添加，且插入位置正确。
- 已排序内拖拽可重排，插入缝隙反馈准确。
- 已排序 -> 未排序拖拽可移出。
- 拖拽时容器高亮、插入缝隙亮蓝色可见；结束后反馈清理干净。
- 提交流程与排名结果正确，无重复/丢失 commentary。

### 7. 拖拽边缘自动滚动（补充）
- 目标：拖拽卡片时，若鼠标停留在列表容器的上/下边缘附近，列表自动向上/向下滚动，便于跨屏排序。
- 触发规则：
  - 仅在拖拽进行中生效（`state.isDragging=true`）；
  - 仅对当前命中的目标列表生效（未排序或已排序）；
  - 边缘触发带宽建议 `24~40px`（可配置 `EDGE_SCROLL_ZONE_PX`）。
- 速度策略（建议渐进）：
  - 鼠标越靠近边缘，滚动速度越快；
  - 速度范围建议 `2~18 px/frame`；
  - 使用 `requestAnimationFrame` 循环而非 `setInterval`，减少抖动。
- 停止条件：
  - 鼠标离开边缘带宽；
  - 到达列表顶部/底部；
  - `drop` / `dragend` / `dragleave` 到非目标容器。
- 实现步骤：
  - [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
    - 新增状态：`autoScrollListEl`、`autoScrollRafId`、`pointerClientY`。
    - 在 `dragover` 内更新 `pointerClientY` 并计算是否进入边缘区。
    - 新增 `startAutoScroll(listEl)` / `stopAutoScroll()`：
      - 在每帧读取容器 `getBoundingClientRect()`；
      - 根据 `pointerClientY` 与上下边缘距离计算方向和速度；
      - 调用 `listEl.scrollTop += delta`。
    - 在 `drop/dragend` 统一调用 `stopAutoScroll()` 清理。
  - [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
    - 可选新增边缘提示态（如顶部/底部淡蓝渐变遮罩）提高可预期性。
- 兼容约束：
  - 自动滚动仅影响目标列表，不允许带动页面或另一个列表滚动。
- 与“滚轮作用域控制”互不冲突：拖拽期间以拖拽自动滚动优先。
- 与插入缝隙计算同步：滚动后持续刷新 `dropIndex`。

## 卡片样式与排序效率优化计划（补充）

### 1. 需求重述（优化后）
- 取消卡片中的“播放解说”按钮，避免重复控件；直接使用音频条原生播放/拖动能力。
- 压缩音频条视觉高度，降低单卡占用空间，提高单屏可见卡片数量。
- 解决“已排序区太短、调整顺序需要长距离滚动”的效率问题。

### 2. 卡片样式优化（视觉层）
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 删除 `data-solo-for` 按钮渲染与相关文案更新逻辑。
  - 保留音频 `<audio controls>` 作为唯一播放入口。
- [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
  - 调小卡片纵向密度：
    - `.card` `padding`、`gap` 适度减小；
    - `.card__header` 与 `chip` 间距收紧；
    - `.textBox` 默认高度降低（保留展开能力）。
  - 缩小音频条外观：
    - 对 `audio` 设置较小 `height`（不同浏览器允许范围内）；
    - 将音频条置于紧凑容器中，减少上下留白。

### 3. 排序效率优化（交互层）
- 方案 A（推荐，优先实现）：已排序区“置顶工具条”
  - 在已排序列表头部增加“快速移动”操作：
    - `置顶`、`置底`、`上移5位`、`下移5位`；
    - 仅对当前选中卡片生效（点击卡片即选中）。
  - 价值：大幅减少长距离拖拽与滚动次数。
- 方案 B（推荐，优先实现）：目标索引输入/跳转
  - 在已排序区提供“移动到第 N 位”小输入框（回车生效）。
  - 价值：长列表时一步到位，避免反复滚动。
- 方案 C（增强，可选）：排序区“压缩视图”
  - 支持切换“紧凑模式”：
    - 默认仅显示标题+音频条；
    - 文本折叠为单行摘要，点击展开详情。
  - 价值：同屏显示更多卡片，拖拽路径更短。
- 方案 D（增强，可选）：拖拽时迷你导航
  - 拖拽中显示浮层提示“当前位置/总数”，并提供“滚到顶部/底部”热区。
  - 价值：跨屏重排更快，定位更明确。

### 4. 结构与行为建议
- 未排序区保持信息完整（便于判读）。
- 已排序区默认启用“紧凑展示 + 可展开详情”，重点服务“快速调序”。
- 保留当前按钮与拖拽并存策略，但减少非必要控件（先去“播放解说”按钮）。

### 5. 压缩视图详细规划（方案 C 细化）
- 交互目标：
  - 已排序区默认进入“紧凑模式”，优先服务快速调序；
  - 未排序区保持现状（信息完整）；
  - 用户可一键切换“紧凑/完整”两种视图（仅作用于已排序区）。
- 卡片在紧凑模式下的结构：
  - 第一行：序号徽标 + 标题 + 核心按钮（移出/上移/下移）；
  - 第二行：音频控件（瘦身）；
  - 第三行：文本摘要单行（`line-clamp: 1`），末尾省略号；
  - 详情默认折叠，不渲染全文块；点击摘要或“展开”后显示全文。
- 展开策略：
  - 单卡独立展开（推荐）：允许对某一条查看全文，不影响其他卡片紧凑状态；
  - 可选“单开模式”：展开新卡片时自动收起上一卡，减少纵向占用。
- 状态模型（前端）：
  - 全局：`rankedCompactMode: boolean`（默认 `true`，存 `localStorage`）；
  - 卡片级：`expandedRankedIds: Set<string>`（记录已展开详情的已排序卡片）。
- 实现步骤：
  - [ui/index.html](D:\Study\Programming\etrip\etrip心理\arena\ui\index.html)
    - 在“已排序”列头新增紧凑模式开关（小型 toggle，不占大空间）。
  - [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
    - 渲染时按 `where==="ranked" && rankedCompactMode` 分支输出紧凑布局；
    - 文本摘要提取函数：
      - `txt`：取首行/前 40~60 字；
      - `json` 分段：取首段文本；
      - 统一去空白与换行。
    - 点击摘要切换单卡展开状态；
    - 与拖拽并存：展开/收起不影响 `draggable` 与 drop 计算。
  - [ui/style.css](D:\Study\Programming\etrip\etrip心理\arena\ui\style.css)
    - 新增 `.card--compact`、`.textSummary`、`.textSummary--expanded` 样式；
    - 紧凑模式下收紧 `padding/gap`，缩短音频区高度。
- 回归约束：
  - 紧凑模式不影响提交顺序、拖拽排序、按钮排序；
  - 展开状态仅 UI 层，不写入后端；
  - 切换任务后可保持模式开关，卡片展开状态建议按任务重置。

### 6. 实施优先级（更新）
1. 移除“播放解说”按钮 + 压缩音频条与卡片间距（低风险、立竿见影）。
2. 上线“已排序区默认紧凑模式 + 单卡展开详情”（本次重点）。
3. 增加“移动到第 N 位”与“置顶/置底/±5位”快捷操作（高收益）。
4. 视效果再决定是否加拖拽迷你导航（可选增强）。

### 7. 验收清单
- 卡片中不再出现“播放解说”按钮，音频条仍可正常播放与拖动。
- 单屏可见卡片数量提升，滚动频率明显下降。
- 已排序区默认紧凑模式，文本默认单行摘要；点击后可展开详情。
- 切换紧凑/完整模式后，拖拽插入缝隙与按钮排序均正常。
- 长距离调序可通过快捷操作在 1~2 次内完成。
- 按钮排序、拖拽排序、提交流程与音视频联动无回归。

## 单一文本主导模式改造计划（去掉音频/文本/混合按钮）

### 1. 目标与原则
- 业务目标：每条解说必须有文本；音频是可选参考信息，不再作为独立标注模式。
- 产品行为：全站统一为“文本主导+可选音频辅助”，用户不再选择 `audio/text/both`。
- 兼容策略：前后端逐步收敛到单一模式，保留历史数据可读，不新增多模式入口。

### 2. 数据与清单规范
- `manifest` 中每条 commentary：
  - `text.path` 必填；
  - `audio.path` 可空；
  - `source/language/commentary_id` 等字段保持不变。
- 前端渲染规则：
  - 有音频：显示音频控件卡片；
  - 无音频：不渲染音频控件，仅显示文本与摘要。

### 3. 普通用户端改造（标注页）
- [ui/index.html](D:\Study\Programming\etrip\etrip心理\arena\ui\index.html)
  - 删除模式选择控件（音频/文本/混合下拉或按钮）。
  - 删除与模式相关提示文案。
- [ui/app.js](D:\Study\Programming\etrip\etrip心理\arena\ui\app.js)
  - 移除 `modeSelect`、`STORAGE.mode`、切换事件及相关状态。
  - `getNextTask` 不再传 `mode` 参数（或固定传 `both` 作为过渡）。
  - 提交时 `mode` 固定为统一值（建议 `"both"` 兼容旧库，后续可改 `"text"`）。
  - 卡片渲染继续按 `audio_url` 是否存在决定是否展示音频控件。

### 4. 管理员端改造（统计与导出）
- [ui/stats/match.html](D:\Study\Programming\etrip\etrip心理\arena\ui\stats\match.html)
  - 删除“仅音频/仅文本/混合”切换按钮区。
- [ui/stats/match.js](D:\Study\Programming\etrip\etrip心理\arena\ui\stats\match.js)
  - 移除 `activeTab` 多模式分支，统一展示单一统计视图。
  - 统计列表直接用统一集合（不再按 mode 过滤）。
- [ui/stats/stats.js](D:\Study\Programming\etrip\etrip心理\arena\ui\stats\stats.js)
  - 卡片计数字段从 `audio/text/both/total` 收敛为统一 `total` 展示（保留历史字段兼容读取）。
- 导出入口：
  - 导出按钮保留，但不再暴露 mode 维度选择。
  - 导出文案改为“标注结果导出（文本主导）”。

### 5. 后端接口与统计收敛
- [app/main.py](D:\Study\Programming\etrip\etrip心理\arena\app\main.py)
  - `/api/tasks/next`：忽略或废弃 `mode` 参数，统一走文本主导过滤（有文本即候选）。
  - `_filter_commentaries`：收敛为“只检查文本存在”；音频仅决定是否带 `audio_url`。
  - `/api/judgments`：`mode` 入参改为可选且默认固定值（建议兼容存 `"both"`）。
  - 统计接口：输出结构去多模式依赖（或保留字段但填充统一来源，避免前端改造期间崩溃）。
  - `/api/export`：忽略 mode 过滤参数或标记为 deprecated。
- [app/schemas.py](D:\Study\Programming\etrip\etrip心理\arena\app\schemas.py)
  - 相关 schema 将 `mode` 从强依赖字段降级为兼容字段（保留但不作为业务分支条件）。

### 6. 迁移与发布顺序（建议）
1. 先改前端：隐藏/删除模式按钮，用户只走单一流程。
2. 再改后端：统一过滤与提交默认 mode，保证接口稳定。
3. 最后改管理员页：去 tab、去 mode 导出入口，统一统计口径。
4. 回归后清理遗留代码（`mode` 本地存储、无用分支、无效文案）。

### 7. 验收清单
- 普通用户端看不到音频/文本/混合选择按钮与相关提示。
- 新任务中：有音频的解说显示音频条；无音频的解说不显示音频条但可正常排序与提交。
- 管理员统计页不再按 mode 分 tab，页面数据正常。
- 导出功能正常，JSONL 不依赖 mode 过滤也可得到完整结果。
- 历史已有 judgments 数据仍可在统计与导出中正常读取。

