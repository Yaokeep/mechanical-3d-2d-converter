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

# DXF 工程图 → SW 原生特征模型 .sldprt（Boss/Cut 可编辑特征树，非 STEP 哑几何）
# 需 cad-occt 环境 + SolidWorks 2025 已启动；输出时间戳 sldprt + 中间 CSG STEP
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_sw_features.py CAD/reducer.dxf
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe dxf_to_sw_features.py input.dxf output.sldprt --no-step

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

# 调试小工具
python debug_dxf_views.py CAD/xxx.dxf                          # 按布局区域打印三视图边/圆分布（仅 ezdxf）
/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe debug_measure_step.py a.step b.step  # STEP 体积/bbox/实体数/面类型（需 OCC）
# 注：根目录另有针对特定靶子模型的一次性 debug_*.py（如 debug_top_*.py / debug_bracket_*.py），
# 不入库（untracked），调试完即弃；正式修复应落在 dxf_to_3d_general.py 等主脚本

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
  dxf_to_3d_general.py   — 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，7664 行）
                           核心链: 边图构建→封闭环检测→视图分离(Y+X 间隙)→CSG 体积求交 / 单视图轮廓拉伸
                           CSG: 各视图外轮廓拉伸为棱柱→布尔交集→内部特征布尔减(P0)→投影验证(P1)
                           →注解驱动分析(P2，中心线对称 + HATCH 剖面验证)，全部自动执行
                           命令行: --single-view 强制轮廓拉伸 / --multi-view 强制包围盒
  convert_dwg_to_3d.py   — DXF → STEP 3D 转换流水线（含 DXF 阶梯轴几何解析 + PythonOCC 建模）
  dxf_to_sw_features.py  — 通用 DXF 工程图 → SW 原生特征模型（1040 行，v0.6.6 新）。复用
                           dxf_to_3d_general 的 CSG 重建结果，z 切片环提取→轨迹跟踪→分段
                           （const/cone/vary）→ SW COM 特征建模（凸台序列自底向上+孔切除+材料岛）。
                           关键修复: 方∩圆法兰轮廓（_normalize_loops 弧端点重合判据，防整圆误合成）、
                           φ12 孔与键槽混合环签名断段、凹口段整圆简化+键槽切穿补切。
                           验收: PF60K 特征模型体积 261,875 vs CSG 261,726（+0.06%）/ 基准 261,935（-0.02%）
                           （v0.6.10 后 18 特征全成，此前 CutExtrude7 混合环草图失败）
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
| `CAD/` | 52 个 VBA 宏（含 VerifySW2025_v33~v45 验证系列）、`SW2025_API_REFERENCE.md`、测试样本 DXF/DWG（`20160112` 阶梯轴、`reducer`、`法兰练习`、`图形练习`）、`temp_output/` 闭环验证链工作区（三视图 DXF 迭代样本——含 `bracket_angker_三视图*.dxf`、`spoon_三视图.dxf`、`pf60k_闭环_三视图_20260817.dxf` 等新靶子、`generate_engineering_drawing.py` 等验证工具，源文件入库、输出产物 gitignored）、`test_simple/` 简单用例、`verify_log/` 宏迭代历史 |
| `PDF/` | 空目录（预留放参考 PDF 文档） |
| `三维/` | 闭环验证参考模型（gitignored）：`麒浚传动_PF60K-14-50-70-M4-L2-12.SLDPRT`、`bracket angker.stp`、`spoon.SLDPRT` / `spoon.STEP`、`勺子/`（勺子参考图 + STEP/STL 副本） |
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

版本 v0.6.14（git 最新提交为准；git tag 到 v0.6.14）。代码内版本字符串与 git 同步：`app.py` = `"0.6.14"`、`main_window.py` 窗口标题 = `"v0.6.14"`、关于对话框 = `"v0.6.14"`：

- **v0.6.14**: bracket 闭环验证用户三特征修复——长槽弧端方形、槽端断开、半圆端小孔缺失（用户验收：重建模型 vs `三维/bracket angker.stp` 基准三处错误）。基准真实几何经点分类探明（物理坐标；CSG = 物理 −(63.65,0,22)）：槽缝空腔 y[-1,1] 是通槽 x[74,84]（平底 z=-22、顶斜坡 0→11.7）+ 平台段 x[84,_dcx] z[-12,12] + **弧端竖槽 x[_dcx,·] z[-12,22] 通到主体顶部**——R12 圆柱面（圆心 (89.54,·,0) r12，y[1,7]）是**叉臂端面**（材料边界）不是槽缝底，R9 圆（y[7,10] r9 与 R12 同心）是外带端面，Y 孔 r3 = R12−R9（图纸 R9 弧即直接信号）轴 (89.54,·,0) 贯穿 y[1,10] 双侧并在槽壁 y=±1 开口。根因：① 方形槽端——弧端区域实为通顶竖槽，r7 切带盒/r8 R12 圆柱刀（y[-7.1,7.1] 全高圆柱切割叉臂材料 + 按 R12 半圆底切割）设计均错误；②/③ 缺失孔——r7 刀组虽已切割 Y 孔但被带切盒错误切割掩盖；r8 修复无效的隐蔽根因是 **Cut(compound) 静默部分失败**（链式 Fuse 累积成 multi-solid compound 后 Cut 只部分生效——Y 孔被切、R12 不生效）。修复（r9 刀组重写）：竖槽 box y[-1.05,1.05] z[-12.3,22.3] 通顶；叉臂/外带材料由主体棱柱与圆盘重叠天然提供，**反向刀**（box − 圆柱，BRepAlgoAPI_Cut(box, cyl)）只切圆盘外角部材料（R12 反刀 ×2 y[1.05,7]/[-7,-1.05]、R9 反刀 ×2 y[7,10.8]/[-10.8,-7]）；Y 孔刀 ×2 圆柱 r=3 贯穿 y[1.05,10.8]；**11 个部件各独立 append 到 all_holes**（不再链式 Fuse）。验证：点分类 19/19 与基准一致（(160,0.5,40) OUT 竖槽通顶、(160,5,26) IN 叉臂、(160,9,26) IN 外带、(162,9,30) OUT 圆盘外角部、(150,1.5,20) IN 槽壁外主体）；bracket compare **−389.77（−0.20%）**（多余 1,752.23 / 缺失 1,807.17 / bbox 203.30×51.00×44.00 vs 基准 203.32×51.01×44.01），优于 v0.6.12 基线 +1968.59 绝对值（基线多余 3,308/缺失 1,339 大部分被本次刀组修复覆盖；剩余差异分布 z[0,10] 净 −241.6 / z[10,22] +60.7 / z[22,34] +246.2 / z[34,44] +294.5 属塔区/豁口等已知信息论局限）；回归套件 6/6；PF60K 无 WELD 262,441.55 与 v0.6.13 验收逐位一致（零回归）。诊断打印（[DBG槽]/[DBGcut]/[DBG刀] 块 + 4 处诊断）已清理，清理后重建与清理前逐位一致
- **v0.6.13**: 隐藏整圆按线型跳过的通用缺陷修复（用户验收：20260817 第一版 PF60K 图纸重建 60×60 丢法兰、体积 +28.5%，与基准差别太大）。根因：v0.6.3 设计注释明确"隐藏整圆**保留**"（孔/台阶圆是 P0 刀具来源、外环恢复依据），实现却按 SKIP_LINETYPES 跳过显式 HIDDEN 线型的圆（含编辑事故死代码）；v0.6.11 只修了图纸生成侧（model_to_drawing 不再写显式 HIDDEN），解析侧未修——旧图纸 24 个圆中 16 个 HIDDEN（含 r30 主体外圆）被跳 → CSG 60×60。修复：CIRCLE 只按图层关键词跳过（中心线/构造层等），不再看线型——解析器宽容生成器差异，不依赖图纸版本。验证：20260817 旧图纸 336,480 → 262,441.55（bbox 80×80 恢复，与 v2 修复后图纸重建**逐位一致**）；bracket +1968.67 vs 基线 +1968.59 零回归；reducer 正常；回归套件 6/6
- **v0.6.12**: bracket angker 闭环验证驱动的棱柱居中量可信度门控修复（两回归修复）——bracket 迭代（`三维/bracket angker.stp` → 三视图 DXF → CSG 重建 → compare_models）期间居中量从"棱柱自身 bbox X 中心"改为"视图分离区域 bbox X 中心"引入两个回归（HEAD 1bee763 两用例均 PASS）：
  - **回归① block_3view FAIL**（体积 125,363 vs 黄金 167,196.20、X=77.5 vs 100）：`_separate_views_2d` 的 X 聚类阈值 `max(30, 宽×0.2)` 不拆分同 Y 层的 front/side（间隙 15<30）→ front 区域被 side 污染 X[0~145]、中心 72.5 ≠ 环中心 50 → 棱柱位移 −22.5
  - **回归② 图形练习 0 实体崩溃**：side 外轮廓是三角形（`_extract_rings_impl` len(vs)<4 跳过）走 bbox 回退分支；side 变换把 DXF X 映射到 3D Y、3D X 是拉伸轴，区域 X 中心沿拉伸轴平移 → 棱柱 x[−2415,−2107] → 三棱柱不相交 → `_common_chain` 只查 IsDone 不查空 → 0 实体 STEP → analyze_step TypeError
  - **修复**：① `outer_trusted` 可信度标志（5 个面选择决策点捕获：环路径/面路径覆盖 ≥50% 校验通过才可信，bbox 回退/front 跨越裁剪/晚期回退均不可信）；② front/top 共享轴同伴一致门控 `_use_own_cx`（面 X 中心与同伴视图区域 X 中心差 ≤3mm 用自身中心——区分"外环残缺"（bracket top 缺叉臂，面中心 125.5 ≠ 同伴区域 103.65 → 区域中心）与"区域污染"（block front 面中心 50 = 同伴区域 50 → 自身中心））；③ side 恒用自身中心（拉伸轴对区域中心无意义）；④ `_common_chain` 空形状加固（TopExp_Explorer 查 SOLID，空则 WARN + 放弃求交走回退链）
  - **验证**：block_3view 167,196.17 / 图形练习 72,000.00（bbox 全部精确、实体=1）；bracket compare +1968.67 vs 基线 +1968.59（零回归，需 `CSG_WELD=1` 与基线同环境——两遍环提取焊接 HLR 碎段，top 环从 78% 残缺升级为完整环）；PF60K 三视图 DXF 重建 336,480.12 与 HEAD 逐位一致（该 DXF 与基线验收 −0.08% 所用 v2 图纸不一致，属图纸版本遗留，非代码改动）；回归套件 6/6
  - **同期并入的 bracket 迭代机制**（工作区累积，详见代码注释）：台阶收腰刀、矩形内腔刀（front 隐藏竖线长带对 + top 隐藏水平线对联合证据）、隐藏水平线收录、CSG_WELD 微边链端点焊接、top x 镜像检测、自交环淘汰、P2 圆心所属视图判定（top>front>side，side 圆跳过）、外轮廓圆剔除圆心位置匹配、凸台条带补丁（后期 Fuse）；`model_to_drawing.py` 视图间隙动态化（固定 50 在宽图上不够——bracket front+side 簇宽 308 → 阈值 61.6 致 side 并入 front，改 gap = max(50, front 宽×0.35)）；`compare_models.py` 增加 `--dx`/`--dy` 平移对齐。已知残留：bracket 净差 +1968.59（多余 3308/缺失 1339，凸台 z[22,24] 两侧槽无信号等，信息论局限注释在代码中）
- **v0.6.11**: 闭环验证链两项工具修复（真实 SLDPRT → 图纸 → 重建全链路重跑验收，体积差 −0.08%）
  - `model_to_drawing.py` 线型 bug：显式 `linetype: "HIDDEN"` 命中 dxf_to_3d_general 的 SKIP_LINETYPES，16 个隐藏层整圆被跳（v0.6.3 设计是隐藏整圆**保留**——孔/台阶圆是 P0 刀具来源、外环恢复依据），闭环重建 +28.46%（CSG 60×60 丢法兰 φ80、P0 仅 9 刀）。修复：实体只设 layer 不设 linetype（BYLAYER），与 generate_engineering_drawing.py 完全一致
  - `compare_models.py` 重写：实体材料域 bbox（逐层 Common 扫描，绕开 SW 导出零厚度悬挂面片/游离顶点伪影）+ solid×solid 顺序布尔切割（compound 整体作刀具静默失效）+ IsDone 校验/ShapeFix 重试 + `--dz`/`--split` 逐段拆分
  - `dxf_to_sw_features.py` 横幅版本 v0.1 → 当前版本

### ✅ 已完成实现

- **GUI 骨架**：菜单栏/工具栏/Dock 面板，2D 视口（QGraphicsView 多视图布局框架），亮色/暗色主题
- **SolidWorks 2025 COM 集成**：`sw_driver.py`（888 行）— 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存，7/7 API 全部调通
- **DXF→SW 全流程建模**：`sw_shaft_builder.py`（1063 行）— 所有 6 个特征全部正确创建：
  - 旋转基体 (Revolve-ShaftBody)
  - 端面倒角 (Chamfer-LeftEnd / Chamfer-RightEnd) — 按 DXF 检测尺寸
  - 阶跃过渡圆角 (Fillet-Transitions) — 按 DXF 检测半径
  - 键槽切除 (Keyway-N) — Python COM FeatureCut3(26参数)
- **`dxf_to_sldprt.py`**：完整 — 命令行参数支持、DXF 几何参数自动检测、时间戳输出文件（防 SW 占用）
- **`convert_dwg_to_3d.py`**：完整 — 使用 PythonOCC 进行 DXF→STEP 3D 实体建模（旋转体 + 键槽布尔减运算），OCC 懒加载设计使 DXF 解析可独立使用
- **`dxf_to_3d_general.py`**（7664 行）：通用 DXF 工程图 → 3D STEP + SW .sldprt。核心算法链：边图构建 → 封闭环检测 → 视图分离(Y+X 间隙) → CSG 体积求交 / 单视图轮廓拉伸。
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
  - v0.6.5 (P3.5): 顶段凸台圆柱截形 — φ17 凸台方形化根因修复。根因：凸台在 front/side 棱柱中只有 17 宽矩形投影（凸台段竖线高 0.9mm < `_vertical_hole_profiles` 段高阈值 1.0 被过滤，`_profile_depths` 无凸台段），CSG 交集产生 17×17 方柱，P0 帽判据只跳过切割（Cut 会削掉凸起）却无截形机制。修复：P3.2 后新增凸台截形块——直接扫 front/side 竖线对（阈值 0.5），段顶贴视图顶且段浅的圆为凸台（深孔 R6 顶贴顶但段深 >4 排除、贯穿孔贴底排除、r8/r8.5 邻圆同扫中截形半径取竖线对实测宽）；只切凸台段方形角部（凸台段盒 ∩ r8.5 圆柱外材料），全程 Common 会把整个主体截成圆柱。定量：凸台段多余 721→0.4，凸台 z[69.5,70.4] 缺失仅 1.8（= 键槽 0.5 深差 4×0.5×0.9）
  - 信息论局限（图纸无信息，无法修复，代码注释已说明）：F 段顶 3mm 环（φ42 孔壁竖线被 HLR 消除）；R8 vs R8.5 凹槽半径差（重建按图纸标注 φ17）；φ3.3 沉头锥（沉头外圈 R2.75 与 φ5.5 顶面孔投影完全重合，top 视图无法区分）；φ3.3/φ5.5 孔位 0.1mm 画图精度差（DXF 17.2 → ±24.8 vs 基准 ±24.7）
  - 注：v0.6.5 起文件内版本字符串（docstring/横幅）已统一为 v0.6.5，与实际功能一致
  - v0.6.8: 底面多层圆环台阶伪影根源修复（用户验收：重建模型底面有基准没有的多层圆环台阶）。根因链：① φ42 孔壁竖线画在隐藏线图层被 parse_dxf_edges 过滤 → F 段派生退化为锥面噪声对 → P3.2 整块错误；② 隐藏线并入后岛/孔分类信号反了（r16 材料岛被当孔、r6 φ12 孔被当岛）→ 新增可见壁/隐藏壁分类（可见孔壁竖线对与 F 段重叠=真孔、仅隐藏线壁=内部材料岛、无竖线=信息论回退）；③ 修复 8：P3.5 泛化新增底面凸台圆柱截形（F 段顶上方浅段识别 φ16 凸台 z[-22~-17]，Fuse r8 圆柱 + 内切方角块切除——锥面裁剪后凸台段是完整盘截面，Cut 角块式会删盘 r[8,30] 环带致实体断裂体积 −15.5k）；④ 补刀凸台段跳过（段底接 F 段顶且段浅的段是凸台）；⑤ P0 凸台面跳过。验收：中心链 −42.45 层 [40,21,16,7] 与基准完全一致，体积 261,894 vs 基准 261,935（−0.02%），1 实体，回归套件 6/6
  - v0.6.9: 内侧假材料柱/顶侧环带缺失/凸台孔堵塞三项通用根因修复（用户验收：内侧多余环形纹路 + 一侧环形结构丢失）。① 台阶环刀底余量 1.0→0.1——段底即台阶腔底，段底下方是台阶盘 r[25,40] 环带真材料，越界余量把腔底下方盘环带误切（PF60K 顶段缺失 1,518→153，余 0.05~0.1mm 为竖线对推导精度）；② 环刀芯融合加段底相接判据（芯段底须与刀段底相接 ±0.5）——芯段底明显高于刀段底的是刀内嵌套孔（φ14 孔底 −42.5 vs φ42 刀底 −43.5），旧逻辑融合实心芯柱把孔刀已切的孔填实（假 r7 材料柱，多余实体 V=1851.9），且芯柱位置改用匹配圆真实圆心（半圆刀 bbox 中心偏移 r/2 的错位同步修复）；③ 凸台延续下方同轴孔——P0 帽判据跳过凸台切割后 Fuse 实心圆柱把贯穿凸台的孔堵死（基准凸台是 r[7,8] 环形柱），新增通用规则：同轴孔段顶与凸台段底相接（±1.5）→ 孔延续切穿凸台段；④ 凸台刀顶余量 0.75→0.1——旧余量越界把凸台顶上方主体 r7 材料误切 0.65mm。验收：体积 261,661 vs 基准 261,935（−0.10%，此前 −0.02% 系多余/缺失抵消假象），1 实体，中心链全层 ✓ 或已知信息论差异，回归套件 6/6
  - v0.6.10: 底面沉头孔 + 键槽误检两项通用根因修复（靶子：SW 特征建模 CutExtrude7 FeatureCut3 返回 None 失败 + 重建底面结构与基准薄板实测不符）。① 底面浅段沉头孔化——P3.5 底面块 v0.6.8/v0.6.9 按凸台处理（Fuse r8 圆柱 + 内切方角块切除 + 芯孔切穿凸台）产生 r[7,8] 环形柱 + 16×16 方井，体积与基准仅差 16mm³ 骗过体积验收，但结构错误（基准逐 2mm 薄板 π(30²−8²)·2=5,253.6 精确吻合，为 φ16 沉头孔 z[0~5] 非凸台）且 SW 特征建模 8 边混合环草图开环拉伸失败；通用规则：F 段顶上方浅段 = 同轴孔沉头——半径取竖线对实测宽（r8.5 邻圆误匹配候选同段去重取小半径排除），直接切孔，沉头段底与下方同轴孔段顶相接（±1.5）时刀底取孔段顶（台阶面共面）；② 键槽检测槽壁竖线必须与孔壁竖线 y 范围重叠（`_detect_keyway` 内部判据）——同轴远处孔的键槽槽壁投影（顶段 φ12 键槽孔槽壁 x=±2）会被底部 φ14 孔误拾成键槽（基准 z[-2,0] 薄板 5,347 = π(30²−7²)·2 精确整圆无键槽），槽刀顶 z_top+1 越界伸入沉头段 1mm 产生 5 边槽口混合环伪影。验收：CSG 逐 2mm 薄板与基准全段吻合，体积 261,726 vs 基准 261,935（−0.08%）；SW 特征模型 18 特征全部创建成功（CutExtrude7 修复），体积 261,875 vs 基准 261,935（−0.02%）；回归套件 6/6。已知残留：顶段角凸 16 边棱柱近似差 −156（基准 z[66,68] 板 4,444 vs CSG 4,288，16 边多边形 vs R40 真弧系统差）
- **`dxf_to_sw_features.py`**（1040 行）：DXF 工程图 → SW 原生特征模型（可编辑特征树：Boss-Extrude/Cut-Extrude/Revolve）。核心链：复用 `dxf_to_3d_general.convert_dxf_to_3d` CSG 重建 → z 切片环提取（圆/线/弧分类）→ 环轨迹跟踪分段 → 段分类（const 拉伸 / cone 旋转 / vary 细分）→ SW COM 特征建模（凸台序列自底向上 + 孔切除 + 材料岛 + 锥面旋转凸台）。验收（PF60K 法兰盘，18 特征）：体积 261,875 vs CSG 261,726（+0.06%）/ SW 基准 261,935（-0.02%）
  - v0.6.6: 方∩圆法兰轮廓修复 — `_normalize_loops` 整圆合成增加弧端点几何重合判据（原先仅角度区间连续性，方∩圆 4 弧被直线隔开、角度伪连续 → 误合成整圆 → SW 拉伸纯圆多出 4 弓形角，体积偏差 +44,803 主因）；φ12 孔与键槽相交混合环签名断段（原中心+半径匹配把混合环并入键槽矩形轨迹，φ12 孔漏切 -3,269）；凹口外环段（键槽切穿凸台）整圆简化 + 对应 cut 段深度延长补切（混合环线-弧 0.2mm 组装间隙致 SW 草图开环拉伸失败）
  - v0.6.7: 通孔切穿修复 — 孔切除统一 `depth-0.1` 微缩会让通孔（孔底=实体底面）留 0.1mm 皮，把底面开口（r25 中心孔 + 4 定位角孔）整个封住（用户验收：另一面多层圆环台阶与定位孔藏在内部）；改为通孔 `depth+0.05` 微超切穿（贯穿切除 SW 自动截断到实体边界），盲孔保持微缩。底面逐层截面与 CSG 基准完全一致。配套：`sw_driver.rebuild()` 增加 ForceRebuild3(True) 二次重建 — SW2025 惰性重建下仅 False 一次后立即 SaveAs3 导出 STEP 只输出草图几何（6.8KB 草图盘，模型看似被切空），双重建后导出完整实体
  - SetAddToDB 行为限制（实测 SW2025）：孔切除草图用 `_sketch_loop(no_snap=True)`（SetAddToDB 绕过草图推理捕捉，键槽矩形角部距截面圆边 0.04mm 会被吸附畸变致 FeatureCut3 None）；**boss 草图必须 no_snap=False**（SetAddToDB 模式线端点不自动合并，多线环开环拉伸失败，八边环实测）
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
| `sw_driver.py` | 888 | COM 驱动封装 — 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存 |
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
- **控制台重定向日志是 GBK 编码**：脚本 `>` 重定向输出的日志为 GBK（Windows 控制台默认代码页）。日志混有非 GBK 字符（如 ✓）时 `iconv -f GBK -t UTF-8` 会中途失败，改用 `grep -a`（文本模式）直接读原始文件。
- Windows 环境下 PythonOCC 的 `pip install` 容易失败，务必使用 conda-forge 安装。
- SolidWorks 自动化功能仅限 Windows，需要安装 SolidWorks 2025 和 `pywin32`。
- **`convert_dwg_to_3d.py` OCC 懒加载**: OCC 导入已改为延迟加载（`_ensure_occ()`），仅需 DXF 解析时（如 `dxf_to_sldprt.py` 引用 `parse_shaft_from_dxf`）不再依赖 PythonOCC。该脚本本身是**完整可用的**——包含 DXF 几何解析、旋转体建模、键槽布尔减运算、STEP 导出。
- **版本号同步**: `src/app.py`（`APP_VERSION`）、`src/gui/main_window.py`（`setWindowTitle` 1 处 + 关于对话框 `main_window.py:535` 1 处，共 2 处）、`CLAUDE.md` 和 git tag 四处版本号需同步。当前 git 为 `v0.6.13`（代码内 `0.6.13`）——提交新版本时务必同步更新这些位置。此外转换器脚本横幅（`dxf_to_3d_general.py` docstring/结尾 print、`dxf_to_sw_features.py` docstring/横幅 print）也含版本字符串。
- **README.md 路线图**: v0.6.5 梳理时已与实际进度对齐（标记已完成版本并指向 CLAUDE.md），后续新增功能时同步更新。
- **`.gitignore`**: 自动排除生成的 CAD 输出文件（`*.SLDPRT`, `*.sldprt`, `*.SLDDRW`, `*.step`, `*.stp`, `*.igs`, `*.iges`, `*.svg`, `*.log`）和 CAD 软件锁文件。`CAD/temp_output/` 下的源脚本（`generate_*.py`、验证工具）与测试样本 DXF/DWG 纳入跟踪，仅输出产物被排除。不要将输出文件加入版本控制。

## Git 约定

- **Commit 消息格式**: `<版本标签>: <简短描述>`，如 `v0.5.0: DXF→SW 全流程打通`
- **Co-Authored-By**: 每次 commit 末尾添加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **自动推送**: 每次本地 commit 后自动 `git push`（用户偏好设置）
- **每次建模使用新文件名**: SW 模型不能覆盖已有文件（防止 SW 进程占用导致保存失败），使用时间戳确保文件名唯一
- **SW 建模后关闭文档**: 每次 SW COM 建模/导出完成后必须关闭旧模型文档（`CloseDoc`）再断开——SW 进程内模型堆积过多会导致 SolidWorks 崩溃。已实现：`sw_driver.py` 的 `disconnect()` 自动先关活动文档（覆盖 dxf_to_3d_general / dxf_to_sw_features / dxf_to_sldprt / GUI）；`sw2025_create_shaft.py` 独立封装同样处理；`sw_export_step.py` 已有 CloseDoc。新增 SW 脚本时收尾必须带文档关闭
