# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

## 常用命令

```bash
# 启动 GUI 应用（完整 3D 功能需在 cad-occt 环境；无 OCC 时优雅降级为占位视图）
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
# 输入 .dwg 时自动调用 tools/libredwg/dwg2dxf.exe 转换
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_3d_general.py CAD/reducer.dxf
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_3d_general.py input.dxf output.sldprt

# DXF/DWG 阶梯轴 → 3D STEP 模型（使用 PythonOCC）
# 需在 cad-occt 环境运行：DXF 解析可脱离 OCC（懒加载），但 STEP 导出必须 OCC
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe convert_dwg_to_3d.py CAD/20160112-181116-09933.dxf output.step

# 简单模型回归套件 — 6 个已验证用例（体积精确匹配 + 逐轴 bbox + 实体数）
# 报告输出 CAD/temp_output/regression_report.txt；--sw 附加 SW 时间戳模型生成
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe run_simple_regression.py
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe run_simple_regression.py --sw

# 命令行直接 COM 驱动 SW 创建阶梯轴（无需 GUI）
python sw2025_create_shaft.py                    # 默认参数建模
python sw2025_create_shaft.py --check            # 仅验证 SW COM 连接
python sw2025_create_shaft.py --dxf CAD/xxx.dxf  # 从 DXF 提取参数
python sw2025_create_shaft.py --no-save --output out.sldprt

# 生成 SW VBA 宏 .bas 文件
python generate_sw_macro.py

# 键槽 VBA 宏生成与测试
python gen_vba_test.py
python keyway_combine_macro.py

# ---- 闭环验证链（真实模型 → 图纸 → 重建 → 定量对比） ----
# 需要 cad-occt 环境；sw_export_step.py 需 SW 2025 COM
python sw_export_step.py 三维/xxx.SLDPRT [out.step]      # SLDPRT → STEP 基准（SW COM）
python model_to_drawing.py input.step [out.dxf]          # STEP → 三视图 DXF（HLR 投影）
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_3d_general.py out.dxf  # DXF → 重建 STEP
python compare_models.py 基准.step 重建.step             # 体积/bbox/布尔差定量对比
python compare_models.py --dz 21.95 基准.step 重建.step  # z 平移对齐（重建系→基准系）
python compare_models.py --dz 21.95 --split -5,0,56.5 基准.step 重建.step  # 逐段拆分多余/缺失
# 图纸侧（SW 工程图 → DXF 导出，生成带三视图的正式图纸）:
python CAD/temp_output/generate_engineering_drawing.py   # SW COM 生成工程图并导出 DXF
```

## 开发环境

本项目工作目录位于 `E:\项目\机械三维二维图互转`，所有路径使用正斜杠 `/`，Python 路径操作使用 `pathlib.Path`。

### 环境安装

```bash
# 推荐使用 conda（pythonocc-core 在 Windows 上通过 conda-forge 安装最稳定）
conda create -n cad-occt python=3.11
conda activate cad-occt
conda install -c conda-forge pythonocc-core=7.7.2
pip install -r requirements.txt
```

实际使用的两个环境：
- `cad-occt`（conda，`/c/Users/yaoshuo/miniconda3/envs/cad-occt/`）— 含 pythonocc-core，运行 `dxf_to_3d_general.py` / `convert_dwg_to_3d.py` 的 3D 建模流程
- `.venv-py311/`（根目录，uv 创建）— 不含 pythonocc-core，也未安装 pytest/ruff；仅用于 DXF 解析、SW COM 等非 OCC 代码

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
            ├─ src/gui/view3d/             (3D 视口，PythonOCC OpenGL 渲染 + view3d_controller 鼠标/键盘交互)
            ├─ src/gui/view2d/             (2D 工程图视口，QGraphicsView)
            ├─ src/gui/dock_widgets/       (项目树、属性面板、输出控制台)
            └─ src/gui/dialogs/            (导入/导出/建模对话框、SW 建模对话框 sw_dialog.py)

src/core/ (核心业务逻辑，与 GUI 完全解耦)
  ├─ model/          (Document、ShapeNode、ProjectionData 数据模型)
  ├─ io/             (格式导入/导出：STEP/IGES/STL/DXF)
  ├─ projection/     (3D→2D 投影：三视图、轴测图、剖面图、HLR 隐藏线消除)
  ├─ reconstruction/ (2D→3D 重建：线框构建 WireMaker、面构建 FaceBuilder、
  │                   拉伸 Extrude、旋转 Revolve)
  ├─ annotation/     (自动尺寸标注：auto_dimension + dimension_calculator)
  └─ sw_automation/  (SolidWorks 2025 COM 自动化驱动 + 参数化建模，✅ 完整实现)

src/utils/ (工具模块：配置管理、日志、线程工作器、单位换算)
resources/styles/ (QSS 主题：light_theme.qss / dark_theme.qss)

根目录独立脚本（不通过 main.py 调用，直接命令行运行）:
  dxf_to_sldprt.py       — DXF 阶梯轴 → SW .sldprt 原生文件（DXF 解析 + SW COM）
  dxf_to_3d_general.py   — 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，3099 行）
                           核心链: 边图构建→封闭环检测→视图分离(Y+X 间隙)→CSG 体积求交 / 单视图轮廓拉伸
                           CSG: 各视图外轮廓拉伸为棱柱→布尔交集→内部特征布尔减(P0)→投影验证(P1)
                           →注解驱动分析(P2，中心线对称 + HATCH 剖面验证)，全部自动执行
                           命令行: --single-view 强制轮廓拉伸 / --multi-view 强制包围盒
  convert_dwg_to_3d.py   — DXF → STEP 3D 转换流水线（含 DXF 阶梯轴几何解析 + PythonOCC 建模）
  sw2025_create_shaft.py — 命令行：直接 COM 驱动 SW 创建阶梯轴（无需 GUI）
  generate_sw_macro.py   — 从 JSON 参数生成 SW VBA 宏 .bas 文件
  gen_vba_test.py        — 生成 VBA FeatureCut3 测试宏 → CAD/SimpleTest.bas
  keyway_combine_macro.py— 生成 + 运行 VBA 键槽布尔减运算宏
```

### 辅助目录

| 目录 | 用途 |
|------|------|
| `.claude/` | `settings.local.json` — 预授权的 Bash 权限列表；`skills/` — 项目级启用的技能符号链接 |
| `.agents/skills/` | 4 个技能：`mechanical-engineer`、`solidworks-cad`（泵叶轮参数化）、`python-code-review`（含 5 个参考文件）、`python-packaging`；仅前两个经符号链接在项目级启用。根目录 `skills-lock.json` 锁定 `mechanical-engineer` 来源 |
| `CAD/` | 52 个 VBA 宏（含 VerifySW2025_v33~v45 验证系列）、`SW2025_API_REFERENCE.md`、测试样本 DXF/DWG（`20160112` 阶梯轴、`reducer`、`法兰练习`、`图形练习`）、`temp_output/` 电机测试、`test_simple/` 简单用例、`verify_log/` 宏迭代历史 |
| `PDF/` | 空目录（预留放参考 PDF 文档） |
| `三维/` | 参考 SLDPRT 模型（`麒浚传动_PF60K-14-50-70-M4-L2-12.SLDPRT`，gitignored） |
| `soldwork/` | SW VBA 宏工作区（`.swp` 工程文件 + `.bas` 测试宏） |
| `tools/libredwg/` | LibreDWG Windows 完整发行版 — `dwg2dxf.exe` 等命令行工具 + Python 绑定；`dxf_to_3d_general.py` 遇 .dwg 输入时自动调用转换 |

### 关键设计约定

1. **数据流**: 所有 CAD 数据通过 `Document` 模型承载，`Document` 是顶层容器，管理 `ShapeNode` 树。`ShapeNode` 封装 `TopoDS_Shape`（OpenCASCADE 核心类型）以及可选的 `metadata` 字典存放非几何信息。

2. **导入器模式**: `src/core/io/` 中所有格式导入器继承 `BaseImporter`，通过 `FormatRegistry` 注册。导入器返回 `Document` 对象。`src/core/io/__init__.py` 在模块加载时自动注册所有内置格式。

3. **3D 视图回退**: `MainWindow._setup_central_widget()` 在 PythonOCC 导入失败时优雅降级为占位标签，不阻塞应用启动。

4. **配置文件**: 用户配置存储在 `~/.cad_converter_config.json`，使用 `AppConfig` dataclass 管理，支持 JSON 序列化。

5. **后台线程模式**: 所有耗时操作（文件 I/O、COM 调用、HLR 计算）使用 `ThreadWorker` 封装，通过 `progress`/`finished`/`error` 信号与 GUI 主线程通信。参考 `sw_dialog.py` 中的 `_sw_build_shaft()` 函数——它在 `QThread` 中运行，`ThreadWorker` 负责线程生命周期管理。

6. **MainWindow 信号连接模式**: 所有菜单/工具栏动作的信号槽连接集中在 `_connect_signals()` 方法中，槽函数命名遵循 `_on_<action>` 约定。

7. **验证准则**: 转换/修复的验收以实际生成的模型为准——每次修改转换代码后运行完整 CLI（生成 STEP + SW 时间戳 .sldprt），不以代码或日志数值吻合作为成功标准。判断几何正确性可加载 STEP 用 `GProp_GProps` 体积 / `BRepAdaptor_Surface` 面类型做定量核对（体积与理论值精确吻合才是真通过）。

## 项目当前状态

版本 v0.6.4（git 最新提交为准；git tag 只到 v0.5.5）。代码内版本字符串与 git 同步：`app.py` = `"0.6.4"`、`main_window.py` 窗口标题 = `"v0.6.4"`、关于对话框 = `"v0.6.4"`：

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
- **`dxf_to_3d_general.py`**（3099 行）：通用 DXF 工程图 → 3D STEP + SW .sldprt。核心算法链：边图构建 → 封闭环检测 → 视图分离(Y+X 间隙) → CSG 体积求交 / 单视图轮廓拉伸。
  - v0.5.4: CSG 体积求交法 — 多视图外轮廓各自拉伸为棱柱 → 布尔交集 → 3D 实体
  - v0.5.5 (P0): 内部特征关联 — 各视图内部闭环（孔/槽）→ 3D 切割工具 → 布尔减运算
  - v0.5.5 (P1): 投影验证回路 — CSG 主体尺寸与视图期望值自动对比，偏差 >30% 自动缩放修正
  - v0.5.7 (P2): 注解驱动分析 — 中心线对称检测 + HATCH 剖面材料验证（`extract_dxf_annotations()` + `csg_reconstruct()` 内 P2 区块）
  - v0.5.8: 三视图分离 X 间隙拆分保持（`_separate_views_2d()`）+ 第三视图 CSG 求交
  - v0.5.9: CSG 视图映射修正为标准正交约定（`_get_view_transform()`：front→XZ/沿Y、top→XY/沿Z、side→YZ/沿X，用满秩 `gp_Trsf.SetValues` 矩阵）——修复系统性 Y/Z 轴向交换（法兰竖盘、块躺倒）；P1 期望尺寸/P2b HATCH 轴向同步更新
  - v0.6.0 (P3): 复杂图纸健壮性 — 以 reducer（263 边真实图纸）为靶子，修复 5 处：
    - 特征坐标映射：CSG 分支凸台/孔从 DXF 绝对坐标改为减去所属视图 DXF 中心（`_dxf_center_x/_y`），修复远离视图中心的凸台落到主体外形成分离实体（reducer 2 实体 → 1 实体）
    - bbox 回退矩形 X 范围与共享轴视图对齐（front/top 互相补齐外轮廓缺失，reducer X=74→95 与期望精确吻合）
    - top 视图特征 Y 映射保留 DXF Y 差异（上下孔不能压到 body_cy，法兰角孔位置）
    - 孤立大圆（半径≥主体最小边 40%）识别为主体外轮廓跳过切除——修复法兰外径被误当孔切穿主体（此前坐标错位掩盖了该误分类）
    - P2a 中心线归属增加 Y 范围检查（top 视图凸台轴心线不再误报为 front 中心线偏移）
  - 单视图回退模式保留（轮廓拉伸+内孔减除）。命令行: --single-view / --multi-view；以上新功能全部自动执行、无新增 CLI 开关
  - v0.6.3 (P3.1~P3.3): 闭环验证链（真实模型 → 三视图 → 重建 → 定量对比）驱动的精度修复，以麒浚传动 PF60K 法兰盘为靶子（总体积偏差 10,355 → 1,079，0.4%）：
    - P3.1: top 视图分体（主体圆棱柱 + 环带棱柱 `prisms_flange`）；主体/环带裁剪到锥面顶分界（`_flange_top_from_ring_vertices` 斜线边信号标定）；顶段角凸补丁（环带棱柱 ∩ 顶段 z 盒，z 范围由竖线对两遍扫描推导：主体级上半部段 ylo → 主体段顶、台阶级 r∈[0.75,0.98]×主体半宽 → 台阶段底）
    - P3.2: F 段派生（法兰孔全高段）、r_f 补刀、φ32 材料岛融合、台阶环刀（顶部台阶内收 r[台阶,主体] 环刀，中心用 top 圆 CSG 坐标——v8 曾用 DXF 坐标切空）
    - P3.3: 调试打印全部清理（27 处 [DBG] 系列）；回归套件 6/6 保持
  - v0.6.4 (P3.4): 用户验收 4 处细节修复 + 锥面过渡裁剪，以 PF60K 法兰盘逐面定量对比为靶子（v9 重建 vs 基准：体积差 −1.05%、多余 721、缺失 3,473、交集 98.7%）：
    - φ12 键槽孔内键槽切除（front 视图槽壁竖线 + 键槽孔竖线对深度段 → 矩形槽刀，`[P0] 键槽刀` 日志）
    - 顶段 R40 角弧恢复（top 外环斜线边 `_cone_cands` 信号 → 顶段角凸补丁源改用 16 边实心棱柱含 R40 角弧，修复 45° 斜切角、圆形突起变方形）
    - φ5.5 顶段孔沉头豁免（P0 顶沉孔段 r∈[0.35,0.95]×环带 r_f 不切，基准顶段孔 z[56.5,66.5] 是贯穿孔非沉头）
    - 网格线清理（布尔差共面碎片面 → `UnifySameDomain` 合并，面数 1734→73）
    - 锥面过渡裁剪（front/side 斜线边信号标定 z_cone 区间，`BRepPrimAPI_MakeCone` 圆锥台裁剪方段 R40→主体 r30，`[P3.1] 锥面过渡裁剪` 日志）
    - 三点过圆 MakeEdge 兼容修复（HLR 顺时针小弧 `end < start` 直接构造产生满圆）
    - compare_models.py 增加 `--dz` z 平移对齐 / `--split` 逐段拆分（逐 solid 求交 + IsDone/体积上限兜底防 box 泄漏）
  - 信息论局限（图纸无信息，无法修复，代码注释已说明）：F 段顶 3mm 环（φ42 孔壁竖线被 HLR 消除）；R8 vs R8.5 凹槽半径差（重建按图纸标注 φ17）；φ3.3 沉头锥（沉头外圈 R2.75 与 φ5.5 顶面孔投影完全重合，top 视图无法区分）；φ3.3/φ5.5 孔位 0.1mm 画图精度差（DXF 17.2 → ±24.8 vs 基准 ±24.7）
  - 注：文件内版本字符串仍为 v2.1（docstring/横幅），git 提交口径曾用 v3.x，实际功能以 git log 为准
- **阶梯轴建模对话框**：`sw_dialog.py`（509 行）— 后台线程建模、进度反馈、参数编辑
- **数据模型**：`Document`、`ShapeNode`、`ProjectionData` 完整实现

### ⚠️ 骨架存在（待集成 PythonOCC）

以下模块有完整的类结构和接口定义，但核心算法标注为 `# TODO`，需集成 PythonOCC 后实现：

- **3D 视图** (`view3d_widget.py`)：已定义 `display_shape()`/`erase_all()`/`fit_all()` 等接口，等待 `OCC.Display.qtDisplay` 集成
- **3D→2D 投影** (`projection/`)：`HLRProjector`、`OrthographicProjector`、`AxonometricProjector`、`SectionView`—所有类结构完整，投影方向/视图标签已定义，等待 `HlrAlgo_Projector` 集成
- **2D→3D 重建** (`reconstruction/`)：`WireMaker`、`FaceBuilder`、`ExtrudeBuilder`、`RevolveBuilder`—流程骨架完整（线框→面→拉伸/旋转），OCC API 调用已注释在代码中
- **文件 I/O** (`io/`)：8 个导入/导出器骨架完整，OCC 调用已注释在代码中；`FormatRegistry` 注册表已完整实现，GUI 导入菜单已接入 `DxfImporter`（当前返回空 Document）
- **自动标注** (`annotation/`)：`AutoDimension` 类结构完整，算法逻辑待实现
- **测试目录**：仅 `__init__.py`（v0.5.6 提交的"测试用例 DXF"指 `CAD/` 下的 `法兰练习`/`图形练习` 样本，非 pytest 用例）

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
- **版本号同步**: `src/app.py`（`APP_VERSION`）、`src/gui/main_window.py`（`setWindowTitle` 1 处 + 关于对话框 `main_window.py:535` 1 处，共 2 处）、`CLAUDE.md` 和 git tag 四处版本号需同步。当前 git 为 `v0.6.4`（代码内 `0.6.4`）——提交新版本时务必同步更新这些位置。
- **README.md 路线图已过时**: README 中的开发路线图停留在项目早期规划阶段（v0.3.0~v1.0.0 均标为未完成），实际进度以本文件和 git log 为准。
- **`.gitignore`**: 自动排除生成的 CAD 输出文件（`*.SLDPRT`, `*.sldprt`, `*.step`, `*.stp`, `*.igs`, `*.iges`）和 CAD 软件锁文件。不要将这些文件加入版本控制。

## Git 约定

- **Commit 消息格式**: `<版本标签>: <简短描述>`，如 `v0.5.0: DXF→SW 全流程打通`
- **Co-Authored-By**: 每次 commit 末尾添加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **自动推送**: 每次本地 commit 后自动 `git push`（用户偏好设置）
- **每次建模使用新文件名**: SW 模型不能覆盖已有文件（防止 SW 进程占用导致保存失败），使用时间戳确保文件名唯一
