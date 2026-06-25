# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

## 常用命令

```bash
# 启动 GUI 应用
python main.py

# 代码质量
ruff check src/            # 代码检查
ruff format src/           # 代码格式化

# 测试（当前为空骨架）
pytest tests/

# ---- 根目录独立脚本（不通过 main.py，直接命令行运行） ----

# DXF 阶梯轴 → SolidWorks .sldprt 原生文件
python dxf_to_sldprt.py CAD/20160112-181116-09933.dxf
python dxf_to_sldprt.py input.dxf output.sldprt

# 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，不限阶梯轴）
# 需要在 cad-occt conda 环境中运行（依赖 PythonOCC）
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_3d_general.py CAD/reducer.dxf
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_3d_general.py input.dxf output.sldprt

# DXF/DWG 阶梯轴 → 3D STEP 模型（使用 PythonOCC）
python convert_dwg_to_3d.py CAD/20160112-181116-09933.dxf output.step

# 命令行直接 COM 驱动 SW 创建阶梯轴（无需 GUI）
python sw2025_create_shaft.py

# 生成 SW VBA 宏 .bas 文件
python generate_sw_macro.py

# 键槽 VBA 宏生成与测试
python gen_vba_test.py
python keyway_combine_macro.py
```

## 开发环境

本项目工作目录位于 `E:\项目\机械三维二维图互转`，所有路径使用正斜杠 `/`，Python 路径操作使用 `pathlib.Path`。

### 环境安装

```bash
# 推荐使用 conda（pythonocc-core 在 Windows 上通过 conda-forge 安装最稳定）
conda create -n cad-converter python=3.11
conda activate cad-converter
conda install -c conda-forge pythonocc-core=7.7.2
pip install -r requirements.txt
```

### 启动应用

```bash
python main.py
```

`main.py` 会自动将 `src/` 加入 `sys.path`，因此所有 `src/` 内的导入都使用 `from src.xxx import ...` 形式。

## 架构设计

### 分层结构

```
main.py (入口，将 src/ 加入 sys.path)
  └─ src/app.py (QApplication 初始化、主题加载)
       └─ src/gui/main_window.py (主窗口，菜单栏/工具栏/状态栏/Dock 面板)
            ├─ src/gui/view3d/             (3D 视口，PythonOCC OpenGL 渲染)
            ├─ src/gui/view2d/             (2D 工程图视口，QGraphicsView)
            ├─ src/gui/dock_widgets/       (项目树、属性面板、输出控制台)
            └─ src/gui/dialogs/            (导入/导出/建模对话框、SW 建模对话框 sw_dialog.py)

src/core/ (核心业务逻辑，与 GUI 完全解耦)
  ├─ model/          (Document、ShapeNode、ProjectionData 数据模型)
  ├─ io/             (格式导入/导出：STEP/IGES/STL/DXF)
  ├─ projection/     (3D→2D 投影：三视图、轴测图、剖面图、HLR 隐藏线消除)
  ├─ reconstruction/ (2D→3D 重建：线框构建 WireMaker、面构建 FaceBuilder、
  │                   拉伸 Extrude、旋转 Revolve)
  ├─ annotation/     (自动尺寸标注)
  └─ sw_automation/  (SolidWorks 2025 COM 自动化驱动 + 参数化建模，✅ 完整实现)

src/utils/ (工具模块：配置管理、日志、线程工作器、单位换算)
resources/styles/ (QSS 主题：light_theme.qss / dark_theme.qss)

根目录独立脚本（不通过 main.py 调用，直接命令行运行）:
  dxf_to_sldprt.py       — DXF 阶梯轴 → SW .sldprt 原生文件（DXF 解析 + SW COM）
  dxf_to_3d_general.py   — 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图）
                           核心: 边图构建→封闭环检测→同心圆聚类→智能拉伸/圆柱体→布尔合并
  convert_dwg_to_3d.py   — DXF → STEP 3D 转换流水线（含 DXF 阶梯轴几何解析 + PythonOCC 建模）
  sw2025_create_shaft.py — 命令行：直接 COM 驱动 SW 创建阶梯轴（无需 GUI）
  generate_sw_macro.py   — 从 JSON 参数生成 SW VBA 宏 .bas 文件
  gen_vba_test.py        — 生成 VBA FeatureCut3 测试宏 → CAD/SimpleTest.bas
  keyway_combine_macro.py— 生成 + 运行 VBA 键槽布尔减运算宏
```

### 辅助目录

| 目录 | 用途 |
|------|------|
| `.claude/` | `settings.local.json` — 预授权的 Bash 权限列表 |
| `.agents/skills/` | 自定义技能：`python-code-review`（含 5 个参考文件）、`python-packaging` |
| `CAD/` | VBA 验证宏（v33~v45）、最终版宏、API 参考、测试 DWG/DXF/STEP 样本 |
| `soldwork/` | SW VBA 宏工作区（`.swp` 工程文件 + `.bas` 测试宏） |
| `tools/libredwg/` | LibreDWG Python 绑定（DWG 格式支持，实验性） |

### 关键设计约定

1. **数据流**: 所有 CAD 数据通过 `Document` 模型承载，`Document` 是顶层容器，管理 `ShapeNode` 树。`ShapeNode` 封装 `TopoDS_Shape`（OpenCASCADE 核心类型）以及可选的 `metadata` 字典存放非几何信息。

2. **导入器模式**: `src/core/io/` 中所有格式导入器继承 `BaseImporter`，通过 `FormatRegistry` 注册。导入器返回 `Document` 对象。`src/core/io/__init__.py` 在模块加载时自动注册所有内置格式。

3. **3D 视图回退**: `MainWindow._setup_central_widget()` 在 PythonOCC 导入失败时优雅降级为占位标签，不阻塞应用启动。

4. **配置文件**: 用户配置存储在 `~/.cad_converter_config.json`，使用 `AppConfig` dataclass 管理，支持 JSON 序列化。

5. **后台线程模式**: 所有耗时操作（文件 I/O、COM 调用、HLR 计算）使用 `ThreadWorker` 封装，通过 `progress`/`finished`/`error` 信号与 GUI 主线程通信。参考 `sw_dialog.py` 中的 `_sw_build_shaft()` 函数——它在 `QThread` 中运行，`ThreadWorker` 负责线程生命周期管理。

6. **MainWindow 信号连接模式**: 所有菜单/工具栏动作的信号槽连接集中在 `_connect_signals()` 方法中，槽函数命名遵循 `_on_<action>` 约定。

## 项目当前状态

版本 v0.5.0（`app.py` = `"0.5.0"`，`main_window.py` = `"v0.5.0"`，git tag 为准）：

### ✅ 已完成实现

- **GUI 骨架**：菜单栏/工具栏/Dock 面板，2D 视口（QGraphicsView 多视图布局框架），亮色/暗色主题
- **SolidWorks 2025 COM 集成**：`sw_driver.py`（774 行）— 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存，7/7 API 全部调通
- **DXF→SW 全流程建模**：`sw_shaft_builder.py`（1063 行）— 所有 6 个特征全部正确创建：
  - 旋转基体 (Revolve-ShaftBody)
  - 端面倒角 (Chamfer-LeftEnd / Chamfer-RightEnd) — 按 DXF 检测尺寸
  - 阶跃过渡圆角 (Fillet-Transitions) — 按 DXF 检测半径
  - 键槽切除 (Keyway-N) — Python COM FeatureCut3(26参数)
- **`dxf_to_sldprt.py`**：完整 — 命令行参数支持、DXF 几何参数自动检测、时间戳输出文件（防 SW 占用）
- **`convert_dwg_to_3d.py`**：完整 — 使用 PythonOCC 进行 DXF→STEP 3D 实体建模（旋转体 + 键槽布尔减运算），OCC 懒加载设计使 DXF 解析可独立使用
- **阶梯轴建模对话框**：`sw_dialog.py`（509 行）— 后台线程建模、进度反馈、参数编辑
- **数据模型**：`Document`、`ShapeNode`、`ProjectionData` 完整实现

### ⚠️ 骨架存在（待集成 PythonOCC）

以下模块有完整的类结构和接口定义，但核心算法标注为 `# TODO`，需集成 PythonOCC 后实现：

- **3D 视图** (`view3d_widget.py`)：已定义 `display_shape()`/`erase_all()`/`fit_all()` 等接口，等待 `OCC.Display.qtDisplay` 集成
- **3D→2D 投影** (`projection/`)：`HLRProjector`、`OrthographicProjector`、`AxonometricProjector`、`SectionView`—所有类结构完整，投影方向/视图标签已定义，等待 `HlrAlgo_Projector` 集成
- **2D→3D 重建** (`reconstruction/`)：`WireMaker`、`FaceBuilder`、`ExtrudeBuilder`、`RevolveBuilder`—流程骨架完整（线框→面→拉伸/旋转），OCC API 调用已注释在代码中
- **文件 I/O** (`io/`)：`StepImporter`/`StepExporter`、`IgesImporter`/`IgesExporter`、`StlImporter`/`StlExporter`、`DxfImporter`/`DxfExporter`—注册表和导入器骨架完整，OCC 调用已注释在代码中
- **自动标注** (`annotation/`)：`AutoDimension` 类结构完整，算法逻辑待实现
- **测试目录**：为空骨架

### SolidWorks 自动化模块 (`src/core/sw_automation/`)

| 文件 | 行数 | 职责 |
|------|------|------|
| `sw_constants.py` | 39 | SW 2025 API 枚举常量（经验证的晚期绑定值），来源：`CAD/SW2025_API_REFERENCE.md` |
| `sw_driver.py` | 774 | COM 驱动封装 — 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存 |
| `sw_shaft_builder.py` | 1063 | 阶梯轴参数化建模 — 旋转基体 → VBScript（倒角+圆角）→ Python COM 键槽 |

**SW 模块依赖**: `pywin32>=306` (Windows only)，通过 `win32com.client.Dispatch("SldWorks.Application")` 晚期绑定驱动 SW 2025。

**关键 API 注意**（来源：45 轮 VBA 验证 + Python COM 调试，详见源文件注释）:
- **单位约定**: 所有 SW API 参数使用**米 (meters)**，调用方负责 `mm / 1000` 转换。SW 内部单位设为 MMGS (毫米-克-秒)。**例外**：`SelectByID2` 使用**文档单位（MMGS 下为 mm）**。
- `FeatureFillet3` 的 `Options` 参数在 SW2025 中必须为 `195`（`0` 和 `1` 均静默失败）
- `SelectByID2` Type 大小写：中文 SW2025 中必须用 `"Edge"`（PascalCase），`"EDGE"` 全大写失败；`"FACE"`/`"PLANE"` 大小写不敏感
- `InsertFeatureChamfer` Type=1 参数顺序：`Width=倒角距离(m)`, `OtherDist=角度(弧度)`——与直觉相反
- VBA 晚期绑定下 `On Error Resume Next` 会导致**假阳性**——每次调用前必须 `Set var = Nothing`
- **VBScript 编码**: 必须使用 **GBK** (cscript 使用系统 ANSI 代码页 CP936)，UTF-8-BOM 会导致编译错误
- **混合架构**: 旋转基体（Python COM）+ 倒角/圆角（VBScript 直接 COM）+ 键槽（Python COM FeatureCut3），各自使用最可靠的接口
- **COM None 编组**: 需要 IDispatch* 参数处使用 `NULL_DISPATCH` / `_null_dispatch()` 而非 Python `None`

### 已移除的功能

以下功能已于 v0.3.0 移除，不再维护：
- `convert_pdf.py` — 基于 Zhang-Suen 骨架化的 PDF→DWG 转换脚本
- `src/core/vectorization/` — 光栅→矢量矢量化引擎
- `src/core/io/pdf_importer.py` — PDF 导入器
- `src/core/io/image_importer.py` — 图像矢量化导入器

## 依赖关系

| 包 | 用途 | 安装方式 |
|---|---|---|
| PyQt6 | GUI 框架 | pip |
| pythonocc-core | CAD 内核（OpenCASCADE 封装） | **必须通过 conda-forge 安装** |
| pywin32 | SolidWorks COM 驱动（Windows only，可选） | pip |
| ezdxf | DXF 读写 | pip |
| numpy | 数值计算 | pip |
| pyyaml | YAML 配置文件解析 | pip |
| loguru | 结构化日志 | pip |
| ruff | 代码检查（开发依赖） | pip |
| pytest / pytest-qt | 测试框架（开发依赖） | pip |

## 路径与平台注意事项

- 项目路径包含中文字符，在终端中操作时注意编码。
- Windows 环境下 PythonOCC 的 `pip install` 容易失败，务必使用 conda-forge 安装。
- SolidWorks 自动化功能仅限 Windows，需要安装 SolidWorks 2025 和 `pywin32`。
- **`convert_dwg_to_3d.py` OCC 懒加载**: OCC 导入已改为延迟加载（`_ensure_occ()`），仅需 DXF 解析时（如 `dxf_to_sldprt.py` 引用 `parse_shaft_from_dxf`）不再依赖 PythonOCC。该脚本本身是**完整可用的**——包含 DXF 几何解析、旋转体建模、键槽布尔减运算、STEP 导出。
- **版本号同步**: `src/app.py`（`APP_VERSION`）、`src/gui/main_window.py`（`setWindowTitle`）、`CLAUDE.md` 和 git tag 的版本号需同步。当前为 `v0.5.0`。
- **README.md 路线图已过时**: README 中的开发路线图停留在项目早期规划阶段（v0.3.0~v1.0.0 均标为未完成），实际进度以本文件和 git log 为准。
- **`.gitignore`**: 自动排除生成的 CAD 输出文件（`*.SLDPRT`, `*.sldprt`, `*.step`, `*.stp`, `*.igs`, `*.iges`）和 CAD 软件锁文件。不要将这些文件加入版本控制。

## Git 约定

- **Commit 消息格式**: `<版本标签>: <简短描述>`，如 `v0.5.0: DXF→SW 全流程打通`
- **Co-Authored-By**: 每次 commit 末尾添加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **自动推送**: 每次本地 commit 后自动 `git push`（用户偏好设置）
- **每次建模使用新文件名**: SW 模型不能覆盖已有文件（防止 SW 进程占用导致保存失败），使用时间戳确保文件名唯一
