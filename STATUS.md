# STATUS

> 当前任务的跨会话接力快照。每次更新覆盖旧内容，不追加历史流水；详细设计与实验结果
> 保存在各自产物中。

更新于 2026-08-05。

## 新会话从这里继续

当前优先完成独立 Formula OCR Helper 的打包诊断和真实公式推理，再继续验证“无论文数据库 +
按需 TXT 缓存 + 可选本地公式 OCR”完整闭环。不要把现有开发构建写成已经可发布或已经解决：
源码修复比当前二进制新，最新二进制仍在 PaddleX Predictor 创建阶段失败。

恢复后的第一步是重新构建包含受限异常因果输出的 Helper：

```zsh
FORMULA_OCR_MODEL_DIR=/Users/a123/.paddlex/official_models/PP-FormulaNet_plus-S \
PAPER_COPILOT_SIGN_IDENTITY=- \
scripts/build_formula_ocr_component.sh
```

该构建需要访问 `uv`/PyInstaller 缓存并写入约 2.1 GB 构建目录，不调用付费模型。此前最后一次
重建因 Codex 使用额度限制被拒绝；提示可在 2026-08-10 13:46 后重试。不要绕过该限制。

## 当前已实现

### 按需论文缓存

- 客户端启动和 Agent 预检不批量生成论文正文缓存；Runtime 预检只计算授权 PDF 的
  SHA-256 和页数并生成 inventory manifest，`text` 可为空、`cached=false`。
- `paper-cache status/ensure/page/search` 使用 PDF 相对路径；读取前重算 PDF SHA-256，替换
  PDF 后使用新哈希键。完整 inventory 扫描成功时才清理孤立缓存，扫描失败时不删除。
- PDF cache schema 为 v2，持久正文产物为按需生成的 `layout.txt`，保留换页符物理页边界；
  Unicode 替换字符或私用区字形所在行生成稳定 `cache_slot`。
- Formula OCR 工具使用 `recognize`/`accept` 两阶段协议：识别候选不修改缓存；接受后才创建新
  revision、原子发布 current，并删除同一缓存键的旧 revision。
- 论文目录仍是唯一 inventory，不创建论文结构化字段数据库、全文索引、向量索引或
  embeddings 数据库。

### macOS UI 与安装门控

- 纯文本模型菜单目前直接显示次级说明“公式 OCR 未安装，可在设置中下载”或“已安装本地公式
  OCR”。这不是原先设想的鼠标悬浮框；用户已表示可以接受当前显示效果。
- 设置页“未下载”依据客户端组件目录中的 schema v2 `active.json` 和可执行 Helper 判断。
  `~/.paddlex/official_models/PP-FormulaNet_plus-S` 中仅有权重时仍显示“未下载”，因为主客户端
  不直接执行裸权重。
- 选择模型、指向模型和启动应用均不应联网；只有用户点击设置中的下载按钮后才解析远程
  manifest 并进入复用或下载流程。
- Formula OCR 组件 manifest 已升级为 schema v2，将 Runtime 和
  `PP-FormulaNet_plus-S` 权重拆成两个独立、带归档哈希和目录树哈希的 artifact。
- 安装器按以下顺序复用精确内容：已组装版本、其他已安装版本中的 Runtime/模型、组件自身
  解压缓存、组件自身下载归档、本机 `~/.paddlex/official_models/PP-FormulaNet_plus-S`；只为
  缺失 artifact 发起网络下载。任一来源都必须匹配 manifest 的确定性目录树 SHA-256。
- Runtime 不复用任意 Python 环境；Helper 必须通过代码签名校验。Runtime 和模型全部验证
  成功后才原子写入 `active.json` 并激活。
- 主客户端仍不应包含 PaddlePaddle、PaddleOCR、PaddleX、OpenCV 或模型权重；这些内容只
  属于可选独立 Helper。

## Formula OCR 构建与诊断事实

当前开发产物位于 `build/formula-ocr-component/`：

- 总目录约 2.1 GB，完整开发 Helper 约 1.1 GB。
- Runtime ZIP：`formula-ocr-runtime-macos-arm64-1.0.0.zip`，327,025,746 bytes，
  SHA-256 `565bfa471c8b8a4a91973b598ed6081a7f45038432fe5c3187cd34fabd36d8cb`。
- 模型 ZIP：`formula-ocr-model-PP-FormulaNet_plus-S-1.0.0.zip`，200,176,509 bytes，
  SHA-256 `a06c8a45fefb17e0312152ba2d7d15db0ff750594374494f89c686b2f04660e8`。
- 当前 manifest 为 schema v2；两个 ZIP 完整性检查、ARM64 检查、ad-hoc 代码签名检查和
  Helper `--help` 曾通过。
- 构建脚本已把 Homebrew `libomp.dylib` 复制并签名为 `_internal/libgomp.1.dylib`，并创建
  `_internal/libgcc_s.1.1.dylib -> paddle/libs/libgcc_s.1.dylib` 兼容别名。
- 当前 Helper 产物中已确认存在上述两个动态库入口和 `pandas`。构建脚本不再排除
  `pandas`。

已执行的推理诊断：

1. 最初的打包 Helper 因缺少 `libgomp.1.dylib`、`libgcc_s.1.1.dylib` 失败；构建脚本已修复。
2. 下一次打包 Helper 因 `No module named 'pandas'` 失败；构建脚本已修复并完成重建。
3. 当前最新打包 Helper 在用户提供的设置页截图上已越过上述依赖加载，但约 70–80 秒后在
   PaddleX Predictor 创建阶段返回通用 `DependencyError`，没有暴露内部原因。
4. 同一张截图、同一权重在仓库 `.venv` 源码环境中可以成功创建 Predictor 并返回结果，说明
   本机权重和基础 Python 环境可用；剩余问题集中在 PyInstaller 打包产物。该截图不是公式
   裁剪，成功结果没有作为公式证据保存或接受。
5. `src/paper_copilot/formula_ocr_helper.py` 已加入最多四层、单层最多 400 字符的受限异常因果
   输出。但源码修改时间晚于当前 Helper 二进制，尚未重建进产物，因此当前二进制仍只返回
   通用错误。

## 下一步：按顺序验证

1. 重建 Helper，确认新二进制包含受限异常因果输出；不得复用当前旧二进制声称验证通过。
2. 先用真实论文中的公式裁剪运行打包 Helper。如果仍失败，依据新错误因果只补充实际缺失的
   PyInstaller hidden import、资源或动态库，然后再次重建。
3. 记录真实公式的首次/后续推理耗时，再决定是否调整
   `src/paper_copilot/agents/formula_ocr_tool.py` 当前 45 秒超时；设置页截图的 70–80 秒只能作为
   冷启动风险信号，不能直接代表真实公式耗时。
4. Helper 单独推理通过后，验证 manifest v2 安装：已有本机权重时只复用权重并获取缺失
   Runtime；已有 Runtime 或归档时也分别复用；内容哈希不匹配时拒绝并下载正确 artifact；
   全部校验成功后才产生 schema v2 `active.json`。
5. 验证工具暴露矩阵：纯文本模型 + 已安装 Helper 可见；纯文本 + 未安装不可见；图像模型
   不可见且继续暴露 `inspect_page`。
6. 验证按需缓存：启动/预检只生成 inventory manifest；仅对选中的一篇论文执行
   `paper-cache ensure`；新增、删除、查询和替换 PDF 后缓存与哈希保持一致。
7. 选取带真实 `cache_slot` 的乱码公式执行 `recognize`，确认 revision 不变；人工检查后执行
   `accept`，确认只替换目标 slot、保留其他正文和页边界、旧 revision 被清理，并验证跨会话
   命中。
8. 最后做主客户端静态依赖检查和 UI 网络门控验证。固定 GitHub Release 当前没有可下载正式
   产物；Developer ID 签名、公证及正式发布另行完成。

## 验证边界与剩余风险

- 本轮已完成实际 Helper 构建和若干本地推理诊断；不再沿用旧状态中“尚未构建”的说法。
- 尚未完成打包 Helper 的成功公式推理、客户端安装/复用、`recognize`/`accept` 回填、跨会话
  命中、Swift 构建、Python 测试或完整缓存一致性验证。
- PyInstaller 分析阶段仍可能打印找不到 GCC 运行库的警告，因为兼容动态库在分析后注入；
  只有产物内入口存在、签名通过且实际推理成功，才能判定该问题解决。
- 构建日志还出现过 `transformers` 与 `huggingface_hub` 的兼容警告。当前不能断言它与
  Predictor 失败有关，必须等待受限错误因果输出。
- 原 PDF 始终是公式权威证据；接受 OCR 候选只授权写入派生 TXT，不等于公式数学正确。
- 开发构建使用 ad-hoc 签名，不等同于 Developer ID 签名、公证或发布验证。
- 未请求或未接受任何付费模型/API 调用；本地截图诊断没有持久化为论文证据。

## 工作树事实

- 当前分支为 `main`。Formula OCR 复用、打包兼容和 UI 修改已提交为 `7eb8b17`；本状态文件
  随后的文档提交与该实现提交在 2026-08-05 一并推送到 `origin/main`。
- 实现提交包含 `ARCHITECTURE.md`、`TASKS.md`、4 个 macOS Swift 文件、Formula OCR
  设计文档、构建脚本和 2 个 Python 文件。
- `.gitignore` 是用户此前已有修改，不属于本轮 Formula OCR 实现，继续保留且不要覆盖。
- 构建产物位于 Git 忽略目录，未提交或推送。
- `git diff --check` 当前通过；此前构建脚本语法检查、ZIP 完整性、ARM64、签名和 Helper
  `--help` 检查通过。尚未运行 Swift 构建、pytest、Ruff 或 mypy。

关键入口：

- `src/paper_copilot/shared/pdf_cache.py`
- `src/paper_copilot/agents/paper_copilot.py`
- `src/paper_copilot/agents/library_exec_tool.py`
- `src/paper_copilot/agents/formula_ocr_tool.py`
- `src/paper_copilot/formula_ocr_helper.py`
- `apps/macos/PaperCopilot/Runtime/FormulaOCRManager.swift`
- `apps/macos/PaperCopilot/Views/SettingsView.swift`
- `scripts/build_formula_ocr_component.sh`
- `docs/design/formula_ocr_optional_component.md`
