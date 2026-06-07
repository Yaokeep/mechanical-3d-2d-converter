# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

## 开发环境

本项目工作目录位于 `E:\项目\机械三维二维图互转`，所有路径应使用正斜杠 `/`，Python 路径操作应使用 `pathlib.Path`。

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
  └─ src/app.py (QApplication 初始化、主题加载)
       └─ src/gui/main_window.py (主窗口，菜单栏/工具栏/状态栏/Dock 面板)
            ├─ src/gui/view3d/  (3D 视口，基于 PythonOCC 的 OpenGL 渲染)
            ├─ src/gui/view2d/  (2D 工程图视口，基于 QGraphicsView)
            ├─ src/gui/dock_widgets/  (项目树、属性面板、输出控制台)
            └─ src/gui/dialogs/  (导入/导出/建模对话框)

src/core/ (核心业务逻辑，与 GUI 完全解耦)
  ├─ model/         (Document、ShapeNode、ProjectionData 数据模型)
  ├─ io/            (格式导入/导出：STEP/IGES/STL/DXF)
  ├─ projection/    (3D→2D 投影：三视图、轴测图、剖面图、HLR 隐藏线消除)
  ├─ reconstruction/ (2D→3D 重建：线框构建 WireMaker、面构建 FaceBuilder、
  │                   拉伸 Extrude、旋转 Revolve)
  └─ annotation/    (自动尺寸标注)

src/utils/ (工具模块：配置管理、日志、线程工作器、单位换算)
```

### 关键设计约定

1. **数据流**: 所有 CAD 数据通过 `Document` 模型承载，`Document` 是顶层容器，管理 `ShapeNode` 树。`ShapeNode` 封装 `TopoDS_Shape`（OpenCASCADE 核心类型）以及可选的 `metadata` 字典存放非几何信息。

2. **导入器模式**: `src/core/io/` 中所有格式导入器继承 `BaseImporter`，通过 `FormatRegistry` 注册。导入器返回 `Document` 对象。

3. **3D 视图回退**: `MainWindow._setup_central_widget()` 在 PythonOCC 导入失败时会优雅降级为占位标签，不阻塞应用启动。

4. **配置文件**: 用户配置存储在 `~/.cad_converter_config.json`，使用 `AppConfig` dataclass 管理，支持 JSON 序列化。

## 项目当前状态

版本 v0.3.0，项目已从 PDF 图像矢量化方向转向 **3D↔2D 标准 CAD 互转**：
- **GUI 骨架**：已完成，菜单栏/工具栏/Dock 面板/3D+2D 视口
- **3D→2D 投影引擎**：骨架存在（`hlr_projector.py`、`orthographic.py`、`axonometric.py`、`section_view.py`），待集成 PythonOCC HLR
- **2D→3D 重建引擎**：骨架存在（`wire_maker.py`、`face_builder.py`、`extrude_builder.py`、`revolve_builder.py`），待集成 PythonOCC
- **文件 I/O**：STEP/IGES/STL/DXF 导入导出骨架存在，待完善
- **自动标注**：骨架存在（`auto_dimension.py`、`dimension_calculator.py`），待实现
- 测试目录为空骨架

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
