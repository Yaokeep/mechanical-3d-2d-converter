# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

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

### 代码质量检查

```bash
ruff check src/        # 代码检查
ruff format src/       # 代码格式化
```

### 运行测试

```bash
pytest tests/          # 全部测试（当前测试目录为空骨架）
```

## 架构设计

### 分层结构

```
main.py (入口)
  ├─ generate_sw_macro.py        (独立脚本：从参数生成 VBA 宏)
  ├─ sw2025_create_shaft.py      (独立脚本：命令行 SW 阶梯轴建模)
  ├─ convert_dwg_to_3d.py        (独立脚本：DWG → STEP 3D 转换)
  └─ src/app.py (QApplication 初始化、主题加载)
       └─ src/gui/main_window.py (主窗口，菜单栏/工具栏/状态栏/Dock 面板)
            ├─ src/gui/view3d/        (3D 视口，PythonOCC OpenGL 渲染)
            ├─ src/gui/view2d/        (2D 工程图视口，QGraphicsView)
            ├─ src/gui/dock_widgets/  (项目树、属性面板、输出控制台)
            └─ src/gui/dialogs/       (导入/导出/建模对话框 + SW 建模对话框)

src/core/ (核心业务逻辑，与 GUI 完全解耦)
  ├─ model/          (Document、ShapeNode、ProjectionData 数据模型)
  ├─ io/             (格式导入/导出：STEP/IGES/STL/DXF)
  ├─ projection/     (3D→2D 投影：三视图、轴测图、剖面图、HLR 隐藏线消除)
  ├─ reconstruction/ (2D→3D 重建：线框构建 WireMaker、面构建 FaceBuilder、
  │                   拉伸 Extrude、旋转 Revolve)
  ├─ annotation/     (自动尺寸标注)
  └─ sw_automation/  (SolidWorks 2025 COM 自动化驱动 + 参数化建模)

src/utils/ (工具模块：配置管理、日志、线程工作器、单位换算)
```

### 关键设计约定

1. **数据流**: 所有 CAD 数据通过 `Document` 模型承载，`Document` 是顶层容器，管理 `ShapeNode` 树。`ShapeNode` 封装 `TopoDS_Shape`（OpenCASCADE 核心类型）以及可选的 `metadata` 字典存放非几何信息。

2. **导入器模式**: `src/core/io/` 中所有格式导入器继承 `BaseImporter`，通过 `FormatRegistry` 注册。导入器返回 `Document` 对象。

3. **3D 视图回退**: `MainWindow._setup_central_widget()` 在 PythonOCC 导入失败时会优雅降级为占位标签，不阻塞应用启动。

4. **配置文件**: 用户配置存储在 `~/.cad_converter_config.json`，使用 `AppConfig` dataclass 管理，支持 JSON 序列化。

5. **SolidWorks COM 驱动单位约定**: 所有 SW API 参数使用**米 (meters)**，调用方负责 `mm / 1000` 转换。SW 内部单位设为 MMGS (毫米-克-秒)。见 `sw_driver.py` 文件头注释。

6. **SolidWorks COM 错误处理**: 封装了三层异常 — `SwError`（基础）、`SwConnectionError`（连接失败）、`SwFeatureError`（特征创建失败）。所有 COM 调用通过 `try/except` 包裹，避免挂死 COM 进程。

## 项目当前状态

版本 v0.4.1：

- **GUI 骨架**：✅ 完成 — 菜单栏/工具栏/Dock 面板/3D+2D 视口
- **SolidWorks 2025 COM 集成**：✅ 完成 — 7/7 API 全部调通，`SolidWorksDriver` 封装完整，`ShaftBuilder` 一键生成完整阶梯轴模型（回转体 + 倒角 + 圆角 + 键槽）
- **阶梯轴建模对话框**：✅ 完成 — `sw_dialog.py` 支持后台线程建模、进度反馈、参数编辑
- **3D→2D 投影引擎**：骨架存在（待集成 PythonOCC HLR）
- **2D→3D 重建引擎**：骨架存在（待集成 PythonOCC）
- **文件 I/O**：STEP/IGES/STL/DXF 导入导出骨架存在（待完善）
- **自动标注**：骨架存在（待实现）
- 测试目录为空骨架

### SolidWorks 自动化模块 (`src/core/sw_automation/`)

| 文件 | 职责 |
|------|------|
| `sw_constants.py` | SW 2025 API 枚举常量（经验证的晚期绑定值），来源：`CAD/SW2025_API_REFERENCE.md` |
| `sw_driver.py` | COM 驱动封装 — 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存 |
| `sw_shaft_builder.py` | 阶梯轴参数化建模 — 旋转基体 → 倒角 → 圆角 → 键槽，所有尺寸以 mm 为单位 |

**SW 模块依赖**: `pywin32>=306` (Windows only)，通过 `win32com.client.Dispatch("SldWorks.Application")` 晚期绑定驱动 SW 2025。

**关键 API 注意**（来源：45 轮 VBA 验证）:
- `FeatureFillet3` 的 `Options` 参数在 SW2025 中必须为 `195`（`0` 和 `1` 均静默失败）
- VBA 晚期绑定下 `On Error Resume Next` 会导致 **假阳性**——失败时变量保留上次成功值，每次调用前必须 `Set var = Nothing`

### 根目录独立脚本

| 文件 | 用途 |
|------|------|
| `generate_sw_macro.py` | 从 JSON 参数生成 SW VBA 宏 `.bas` 文件 |
| `sw2025_create_shaft.py` | 命令行工具：直接通过 COM 驱动 SW 创建阶梯轴（不依赖 GUI） |
| `convert_dwg_to_3d.py` | DWG → STEP 3D 转换流水线 |

### CAD/ 目录

存放 VBA 验证宏（`VerifySW2025_v33~v45.bas`）、最终版本宏（`CreateShaft_SW2025.bas`）、API 参考文档（`SW2025_API_REFERENCE.md`）以及测试用的 DWG/DXF/STEP 样本文件。`verify_log/` 子目录存放 v7~v32 的验证迭代。

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
- `tools/libredwg/` 包含 LibreDWG Python 绑定，用于 DWG 格式支持（实验性）。
- SolidWorks 自动化功能仅限 Windows，需要安装 SolidWorks 2025 和 `pywin32`。
