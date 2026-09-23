# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

## 常用命令

```bash
# 启动 GUI 应用（完整 3D 功能需在 cad-occt 环境；无 OCC 时优雅降级为占位视图）
# ⚠️ 实测 2026-08-20：三个环境均未安装 PyQt6，GUI 当前无法启动（需先 pip install PyQt6）。
#    日常开发走下方独立脚本，不经 GUI——GUI 侧核心算法仍是骨架
python main.py

# 代码质量（ruff 只装在 PATH 默认 python 里，两个记录环境都没有）
ruff check src/            # 已知基线 139 告警：F401×73 / F541×46 / F821×14 / F841×5 / E402×1
ruff format src/           # 无 pyproject.toml，全部走 ruff 默认规则

# 测试：tests/ 仅 __init__.py，且三个环境均未装 pytest。
# 本项目的真实回归入口是下方 run_simple_regression.py（几何验收），不是 pytest
pytest tests/

# ---- 根目录独立脚本（不通过 main.py，直接命令行运行） ----
# 凡 import OCC 的脚本都必须用 $PY（cad-occt 环境），下同
PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe

# DXF 阶梯轴 → SolidWorks .sldprt 原生文件（纯 DXF+COM，默认 python 即可）
python dxf_to_sldprt.py CAD/20160112-181116-09933.dxf [output.sldprt]

# 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，不限阶梯轴）
# 输入 .dwg 时自动调用 tools/libredwg/dwg2dxf.exe 转换
$PY dxf_to_3d_general.py CAD/reducer.dxf [output.sldprt]

# DXF/DWG 阶梯轴 → 3D STEP（DXF 解析可脱离 OCC 懒加载，但 STEP 导出必须 OCC）
$PY convert_dwg_to_3d.py CAD/20160112-181116-09933.dxf output.step

# DXF 工程图 → SW 原生特征模型 .sldprt（Boss/Cut 可编辑特征树，非 STEP 哑几何）
# 需 SolidWorks 2025 已启动；输出时间戳 sldprt + 中间 CSG STEP
$PY dxf_to_sw_features.py CAD/reducer.dxf [output.sldprt] [--no-step]

# 简单模型回归套件 — 6 个已验证用例（体积精确匹配 + 逐轴 bbox + 实体数）
# 报告输出 CAD/temp_output/regression_report.txt；--sw 附加 SW 时间戳模型生成
$PY run_simple_regression.py [--sw]

# 跑单个用例：套件无用例过滤开关（只认 --sw）。单用例直接调 convert_dxf_to_3d，
# 绕开 CLI 的 SW 导入；黄金值（体积/逐轴 bbox）见 run_simple_regression.py:38 的 CASES 表
$PY -c "
import dxf_to_3d_general as d, run_simple_regression as r
d.convert_dxf_to_3d('CAD/test_simple/block_3view.dxf', 'CAD/temp_output/_one.step')
print(r.analyze_step(__import__('pathlib').Path('CAD/temp_output/_one.step')))"

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
python debug_dxf_views.py CAD/xxx.dxf          # 按布局区域打印三视图边/圆分布（仅 ezdxf）
$PY debug_measure_step.py a.step b.step        # STEP 体积/bbox/实体数/面类型（需 OCC）
python _render_dxf.py <in.dxf> <out.png> [dpi] [x0 x1 y0 y1]  # DXF → PNG 看图（默认 python）
                                               # 末尾四个参数可局部放大某个视图
# ⚠️ 看图必踩的坑：ezdxf 按 DXF 里存的背景色（本项目图纸是深色 #212830）解析
#   ACI 颜色，而可见轮廓与 HATCH 都带 ACI 7（随背景反转的黑/白）→ 解析成白线；
#   若再自己设白底，主体轮廓就在白底上整体隐形，只剩蓝色隐藏线——会得出
#   "图纸有问题"的错误结论。_render_dxf.py 已用 LayoutProperties.set_colors
#   覆盖成白底黑线配色，别绕开它直接调 Frontend
$PY _make_viewer.py                            # 生成 CAD/temp_output/_viewer/bracket_viewer.html：
                                               # 基准/重建叠加，点选弹框、坐标=基准系 mm——
                                               # 用户目视标记缺陷的入口（v0.6.18 三缺陷即由此而来）。
                                               # 脚本内路径写死 bracket：换重建结果改 main() 里 read_step 的 _3d.step 路径
# 注：上面两个 debug_*.py 是入库的通用工具。针对特定靶子的一次性脚本一律用 `_` 前缀，
# 由 .gitignore 的 `/_*.py`、`CAD/temp_output/_*` 排除，调试完即弃；现存 30+ 个分四类：
# `_probe_*.py` 几何探针（_probe_ysec 逐 y 层截面 / _probe_zsec 水平截面 / _probe_y0 /
# _probe_slot）、`_diag_*.py` 根因诊断、`_csg_*.py` 代码版本备份、`_make_viewer.py`。
# 正式修复应落在 dxf_to_3d_general.py 等主脚本

# 截面叠加图（"图形识别"排查链，两段式——cad-occt 无 matplotlib，默认 python 无 OCC）
$PY _dump_sections.py <step> <tag> [dx,dy,dz]     # OCC 侧：若干截面 → JSON（基准系坐标）
python _draw_sections.py <base.json> <reb.json> <名>   # matplotlib 侧：蓝=基准 红=重建 紫=重合
# ↑ 输出 CAD/temp_output/_viz/<名>_总览.png + 逐个截面大图。PLANES 表写死 bracket 的
#   12 个位置（z5/16.47/30/40、y0/7/9.4、x−18.11/121.89/145/153.19/160），换零件改它。
#   ⚠️ 截面正好切在平面上时，该平面的轮廓会整片出现在截面上 → 看图得出的结论
#   必须用盒探针在实体上复核，否则会把退化伪影当成真差异
$PY _probe_boxes.py [重建step]                    # 盒探针：逐区域量基准/重建的材料体积差

# ---- 闭环验证链（真实模型 → 图纸 → 重建 → 定量对比） ----
python sw_export_step.py 三维/xxx.SLDPRT [out.step]      # SLDPRT → STEP 基准（只需 SW COM）
$PY model_to_drawing.py input.step [out.dxf]             # STEP → 三视图 DXF（HLR 投影）
# ↑ 同时自动输出 <out>_剖面图.dxf：三视图 + 自动选位剖面 + HATCH + 剖切线标记。
#   两个文件分开是必须的——闭环重建把 HATCH 当剖面材料信号、把多余视图簇
#   当独立视图，混在一起会破坏重建。--no-section 可关闭
$PY model_to_drawing.py input.step out.dxf --no-section   # 只要三视图
$PY dxf_to_3d_general.py out.dxf                         # DXF → 重建 STEP（末尾会尝试导入 SW）
$PY compare_models.py 基准.step 重建.step                # 体积/bbox/布尔差定量对比
# ⚠️ bracket 必须带 --dx 63.65：CSG 系 x=物理x−63.65、z=物理z−22，只给 --dz 会残留
#   63.65mm 的 x 平移（净差不受影响，但多余/缺失/重合三项全失真，见下方口径注）
$PY compare_models.py --dx 63.65 --dz 21.95 基准.step 重建.step  # 平移对齐（重建系→基准系）
$PY compare_models.py --dx 63.65 --dz 21.95 --split -5,0,56.5 基准.step 重建.step  # 逐段拆分多余/缺失
$PY compare_models.py --dx 63.65 --dz 21.95 --split -5,0,56.5 --split-axis x 基准.step 重建.step  # 分段轴换 x/y

# CSG_WELD=1：微边链端点焊接 + 两遍环提取取面积大者（门控写成 `os.environ.get("CSG_WELD")`，
# 分别在 weld_chain_ends 调用处与 _extract_rings_impl 的两遍调用处）。
# HLR 生成的图纸易把外环打成碎段，bracket 基线就是在该开关下取得的——
# 与历史数值对比时必须同环境，否则重建结果不可比
CSG_WELD=1 $PY dxf_to_3d_general.py CAD/temp_output/bracket_angker_三视图_v4.dxf
# v0.6.15 起支持三视图+剖面混合图纸：剖面行自动识别为约束棱柱。同一基准下
# 有剖面 +3.81% / 无剖面 +5.02%——剖面棱柱只能按真实截面裁假材料，
# 融合投影丢掉的交界线信号补不回来，见信息论局限表
CSG_WELD=1 $PY dxf_to_3d_general.py CAD/temp_output/bracket_angker_图纸_20260922_剖面图.dxf
# 图纸侧（SW 工程图 → DXF 导出，生成带三视图的正式图纸）:
python CAD/temp_output/generate_engineering_drawing.py   # SW COM 生成工程图并导出 DXF
# ⚠️ 出图侧已知缺陷（2026-09-22 复核）：图纸里 12 处中文标注（"俯视图"/"A—A 剖视
#   全剖 y=0.00"…）用的都是唯一文字样式 `Standard`，其 font='txt'（txt.shx，无 CJK
#   字形）、无 bigfont → 在任何 CAD 里都渲染成方框；标注里的破折号 U+2014 同理。
#   修法：给该样式补 bigfont='gbcbig.shx'（AutoCAD 经典组合），或改用中文 TTF
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

实际存在的三个解释器（2026-09-22 复测，PyQt6/pytest 仍三者皆无；选错解释器是最常见的时间浪费）：

| 解释器 | OCC | ezdxf | pywin32 | PyQt6 | ruff | pytest | 用途 |
|--------|-----|-------|---------|-------|------|--------|------|
| `cad-occt`（conda，`/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe`） | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | 所有 3D/CSG/HLR/对比流程 |
| PATH 默认 `python`（`G:\python\python.exe` 3.13.2） | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | 纯 DXF 解析、SW COM 脚本、ruff |
| `.venv-py311/`（根目录，uv 创建） | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | 无独有能力，实际可不用 |

判据：脚本 `import OCC` → 必须 cad-occt；只 `import ezdxf`/`win32com` → 默认 `python` 即可。
**三个环境都没有 PyQt6**，GUI（`main.py`）当前起不来；也都没有 pytest。

### 启动应用

`main.py` 会自动将 `src/` 加入 `sys.path`，因此所有 `src/` 内的导入都使用 `from src.xxx import ...` 形式。
（当前无环境装有 PyQt6，`python main.py` 起不来；见上表）

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
  dxf_to_3d_general.py   — 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，8957 行）
                           核心链: 边图构建→封闭环检测→视图分离(Y+X 间隙，v0.6.15 起含剖面行识别)
                           →CSG 体积求交 / 单视图轮廓拉伸
                           CSG: 各视图外轮廓拉伸为棱柱→布尔交集→内部特征布尔减(P0)→投影验证(P1)
                           →注解驱动分析(P2，中心线对称 + HATCH 剖面验证)，全部自动执行
                           v0.6.15: 剖面视图识别——剖面行打标 _is_section、父视图匹配、
                           全环枚举（外环−内环）建带孔截面 face 沿父轴向拉伸为剖面棱柱
                           与标准棱柱求交（只会删假材料不会加）；P0/注解消费端全部加
                           _is_section 守卫
                           命令行: --single-view 强制轮廓拉伸 / --multi-view 强制包围盒
  convert_dwg_to_3d.py   — DXF → STEP 3D 转换流水线（含 DXF 阶梯轴几何解析 + PythonOCC 建模）
  section_view.py        — 剖面图生成（结构分析自动选剖切位置 + 半空间裁剪 + 真 HATCH）。
                           被 model_to_drawing.py 调用。三条硬约束写在模块注释里：
                           ① 多实体 STEP 必须逐实体 Fuse（compound 布尔静默部分失败），
                              但**只用于剖面/图纸**——融合后的三视图会让闭环重建从
                              −0.20% 劣化到 +5.02%（交界线是 CSG 的特征信号）
                           ② 剖面投影必须用 HLRBRep_PolyAlgo：含 B 样条/球面的零件被
                              布尔裁剪后，精确 HLR 所有通道返回 0 边（形状本身有效）
                           ③ 剖面线取真实截面 face 的外环+内环 → HATCH，孔洞留白；
                              自检 2D 路径面积 vs OCC 实测面积（bracket 三剖面误差 <0.005%）
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
| `docs/` | `CHANGELOG.md` — v0.5.4~v0.6.18 逐版本根因叙事，三段倒序（主线 v0.6.11~v0.6.18 / dxf_to_3d_general 精度收敛链 v0.5.4~v0.6.10 / dxf_to_sw_features v0.6.6~v0.6.7）。查"某阈值为何是 0.1"这类历史依据时看它 |
| `.claude/` | `settings.local.json` — 预授权的 Bash 权限列表；`skills/` — 项目级启用的技能符号链接 |
| `.agents/skills/` | 4 个技能：`mechanical-engineer`、`solidworks-cad`（泵叶轮参数化）、`python-code-review`（含 5 个参考文件）、`python-packaging`；仅前两个经符号链接在项目级启用。根目录 `skills-lock.json` 锁定 `mechanical-engineer` 来源 |
| `CAD/` | 51 个 VBA 宏 `.bas`（本目录 24 含 VerifySW2025_v33~v45 验证系列 + `verify_log/` 27 个早期迭代；另 4 个在仓库根 `soldwork/`），全部入库、`SW2025_API_REFERENCE.md`、测试样本 DXF/DWG（`20160112` 阶梯轴、`reducer`、`法兰练习`、`图形练习`）、`temp_output/` 闭环验证链工作区（图纸 DXF 迭代样本——`bracket_angker_三视图_v4.dxf` 与 `bracket_angker_图纸_20260922_剖面图.dxf` 是当前两个 bracket 基线、`spoon_三视图.dxf`、`pf60k_闭环_三视图_20260817.dxf`、`generate_engineering_drawing.py` 等验证工具，源文件入库、输出产物 gitignored）、`test_simple/` 简单用例 |
| `PDF/` | 空目录（预留放参考 PDF 文档） |
| `三维/` | 闭环验证参考模型（gitignored）：`麒浚传动_PF60K-14-50-70-M4-L2-12.SLDPRT`、`bracket angker.stp`、`spoon.SLDPRT` / `spoon.STEP`、`勺子/`（勺子参考图 + STEP/STL 副本） |
| `soldwork/` | SW VBA 宏工作区：`.bas` 测试宏（入库）+ `.swp` 工程文件（**未入库**，被 `.gitignore` 的 vim-swap 规则误伤，见下方"路径与平台注意事项"） |
| `tools/libredwg/` | LibreDWG Windows 完整发行版 — `dwg2dxf.exe` 等命令行工具 + Python 绑定；`dxf_to_3d_general.py` 遇 .dwg 输入时自动调用转换 |

### 关键设计约定

**验证准则（最重要）**: 转换/修复的验收以实际生成的模型为准——每次修改转换
代码后运行完整 CLI（生成 STEP + SW 时间戳 .sldprt），**不以代码或日志数值吻合
作为成功标准**。判断几何正确性可加载 STEP 用 `GProp_GProps` 体积 /
`BRepAdaptor_Surface` 面类型做定量核对（体积与理论值精确吻合才是真通过）。

**变更归因**: 图纸与代码同时变过时（典型是"重建数值变了，是修复的效果还是
出图版本的效果"），先 `git stash` 回退代码跑**旧代码 × 新图纸**——与历史基线
一致即证明差异来自图纸，否则才是代码回归。v0.6.18 用此法把净 +202.7 定性为
修复的净加材料效应而非回归。改动刀组这类被多条路径共用的代码后，三视图与
剖面图纸两条基线都要重测——v0.6.18 正是顺带把三视图从 −0.27% 改善到 −0.14%。

以下是 `src/` 侧的设计意图，GUI 接线时遵循（当前均为骨架）：

- **数据流**: CAD 数据统一由 `Document`（顶层容器，管理 `ShapeNode` 树）承载；
  `ShapeNode` 封装 `TopoDS_Shape` + 可选 `metadata` 字典存非几何信息
- **导入器模式**: `core/io/` 各导入器继承 `BaseImporter`、经 `FormatRegistry` 注册、
  返回 `Document`；`io/__init__.py` 在模块加载时自动注册所有内置格式
- **3D 视图回退**: `MainWindow._setup_central_widget()` 在 PythonOCC 导入失败时
  降级为占位标签，不阻塞启动
- **后台线程**: 耗时操作（文件 I/O、COM 调用、HLR 计算）一律用 `ThreadWorker` 封装，
  经 `progress`/`finished`/`error` 信号与主线程通信；范例见 `sw_dialog.py`
  的 `_sw_build_shaft()`
- **信号连接**: 菜单/工具栏信号槽集中在 `_connect_signals()`，槽命名 `_on_<action>`
- **配置文件**: `~/.cad_converter_config.json`，`AppConfig` dataclass + JSON 序列化

## 项目当前状态

版本 v0.6.18（git tag 为准）。代码内三处版本字符串（`app.py:15` /
`main_window.py:28` / `main_window.py:535`）与 git 一致，已核对。
**逐版本根因叙事已迁至 `docs/CHANGELOG.md`**（v0.5.4~v0.6.18）——
本节只留仍在影响决策的部分。

### 当前精度断点

| 靶子 | 重建 vs 基准 | 状态 |
|------|-------------|------|
| PF60K 法兰盘（CSG） | 261,726 / 261,935（−0.08%） | 收敛 |
| PF60K 法兰盘（SW 特征模型，18 特征） | 261,875 / 261,935（−0.02%） | 收敛 |
| bracket angker（三视图） | 净差 +538.38（+0.28%），重合 **98.8%** | 收敛；v0.6.18 刀组修复连带改善（恢复被多切的弧端/球台/弦棱 → 比 v0.6.17 多留 252）。**2026-09-24 挂耳间隙修复后净差从 −267.38 变 +538.38 是修复的必然效应**（挂耳右半实心恢复 +805.6 的缺失减少，见下行；非回归）。遗留：挂耳左半盒外多余 ~457（修复前就有的旧问题，修复后微减至 456.9，基准左半无材料） |
| bracket angker（三视图+剖面图纸） | 净差 +8,112.77（+4.23%），重合 **98.9%** | 用户三缺陷已修复（端头弧/薄壁/挂耳五保护体；净 +202.7 = 修复净加材料效应非回归）。**2026-09-24 用户两处挂耳间隙缺陷（基准(163.08,−9.42,26.09)/(164.80,7.90,23.96)）根因+修复**：`_tor9` 臂环盘 revolve 保护体三错——①轴边画在旋转轴上 MakeRevol 退化生成 53.7% 空心体（顶底圆盘丢、torus 外圈丢）→ 外带反刀（盒−残壳）把正体挂耳芯挖空+外圈切光；②直段画在管心 r9 应为外轮廓 r12；③弧 θ∈[π/2,3π/2] 经 (6,7) 是内轮廓，外轮廓应 θ∈[0,π/2] 经 (12,7)。修复 = ε=0.001 离轴边 + 外轮廓 wire → 实心 100.00%（体积 8,772.80 = 理论 8,772.58）；右半挂耳恢复（107.4→272.0 vs 基准 278.0、0.1→53.3 vs 58.4），净差 +805.0 = 缺失恢复的必然效应。**剩余误差已定位成一块**（2026-09-22 截面叠加图 + 盒探针）：臂区方块 x[96,162]×y[±25] z>27 存活——探针 z[27,33] 重建 2,382.3 vs 基准 1,772.7、z[38,42] 1,588.2 vs 1,181.8，而同区域三视图路径 1,770.1 / 1,180.1 精确。**v0.6.18 证明 `sec_B`/`sec_C` 部分剖面棱柱不可行**：剖面只携带剖切位置零厚度截面信息（B—B 截面 = 两片 9.8×44 壁 862.4，逐 SOLID 探针已证出图侧截面提取正确、无 bug），而管腔沿 x 处处渐变（x[96,106] 实心条 → x[122,128] 中空壁 → x[128,144] 渐实心），图纸不含窗口信号（剖切线只有箭头无贯通线）——任何窗口的全长拉伸都误裁真材料（实测 HATCH 兜底 Fuse 合并后净差 −68.93%）。门控"非全尺寸跳过"即正确行为：HATCH 兜底加面积门控（材料面积 <90% 父 bbox → 跳过），实际只有 `sec_A`(y=0) 生效 |
| 简单模型回归套件 | 6/6 | 绿 |

基准模型在 `三维/`（gitignored，用户私有数据）。bracket 与历史数值对比
必须在 `CSG_WELD=1` 下进行，否则不可比。**跨版本可比的只有"净差"一列**——
早期记录里的"多余 8,836 / 缺失 1,730"是 `--split` 逐段拆分口径，与全量口径
不可直接比较。

⚠️ **口径更正（2026-09-22 全流程重跑发现）**：曾记录的"全量口径 11 万级"
（三视图 112,507.67 / 112,774.01、剖面图纸 118,396.50 / 111,088.01）**是错的**——
那批数是在 `--dz 21.95`、**漏了 `--dx 63.65`** 的情况下量的，混合了 63.65mm 的
x 平移伪影。补上 dx 后同一对模型是：三视图 多余 1,681.28 / 缺失 1,952.90 /
**重合 99.0%**，剖面图纸 多余 8,946.99 / 缺失 1,638.74 / **重合 99.1%**。
净差不受影响（平移保体积），历史"净差"一列仍有效；受影响的只有多余/缺失/重合。
教训：这三项对平移极敏感，报数前先确认对齐，别用净差"看起来对"来反推对齐正确。

### 信息论局限（图纸里没有这个信息，不可修复；代码已就地注释）

- **F 段顶 3mm 环**：φ42 孔壁竖线被 HLR 消除
- **R8 vs R8.5 凹槽半径差**：图纸只标 φ17，重建按标注走
- **φ3.3 沉头锥**：沉头外圈 R2.75 与 φ5.5 顶面孔投影完全重合，top 视图无法区分
- **φ3.3/φ5.5 孔位 0.1mm 差**：画图精度（DXF 17.2 → ±24.8 vs 基准 ±24.7）
- **顶段角凸**：16 边棱柱近似 R40 真弧，系统差 −156（z[66,68] 板 4,288 vs 4,444）
- **bracket 凸台 z[22,24] 两侧槽**：两视图均无信号
- **剖面图纸的三视图是融合投影**：融合抹掉 CSG 交界线信号（同一模型，
  未融合三视图 −0.14% → 融合三视图 +5.02%）。剖面棱柱只能按剖切面真实截面
  裁假材料，融合投影本身丢失的信息补不回来——这不是剖面识别能修的，是
  图纸侧出图方式的选择（闭环链三视图必须用未融合 shape 出图）。
  这份误差的**具体落点**已查明，见精度断点表该行（臂区方块 + 剖面棱柱门控）

碰到落在这张表里的偏差不要继续"修"——先确认图纸是否真的携带该信息，
否则会像 v0.6.10 那样造出体积对得上、结构却错的模型。

### 实现状态

**根目录独立脚本 = 全部完整可用**（各脚本职责与算法链见上方"分层结构"）。
`src/core/sw_automation/` 与数据模型（`Document`/`ShapeNode`/`ProjectionData`）
同样完整：SW 7/7 API 调通，阶梯轴 6 特征（旋转基体 + 左右端面倒角 +
阶跃过渡圆角 + 键槽切除）全部按 DXF 检测尺寸正确创建。

**`src/` 内 GUI 与算法模块仍是骨架**——类结构和接口定义完整，核心算法标注
`# TODO`，OCC API 调用已注释在代码中，待集成：

- `gui/view3d/`（`display_shape`/`erase_all`/`fit_all` 已定义，等 `OCC.Display.qtDisplay`）
- `core/projection/`（`HLRProjector`/`Orthographic`/`Axonometric`/`SectionView`，等 `HlrAlgo_Projector`）
- `core/reconstruction/`（`WireMaker`/`FaceBuilder`/`ExtrudeBuilder`/`RevolveBuilder`）
- `core/io/`（8 个导入/导出器；`FormatRegistry` 已完整，GUI 导入菜单已接
  `DxfImporter` 但当前返回空 Document）
- `core/annotation/`（`AutoDimension`）

⚠️ **GUI 骨架与根目录脚本是两套独立实现**：三视图投影、2D→3D 重建这些能力
在根目录脚本里已生产可用，`src/` 里的同名模块是尚未接线的另一份。改算法请
落在根目录脚本，不要误以为 `src/core/projection/` 是现役代码。

### SolidWorks 自动化模块 (`src/core/sw_automation/`)

| 文件 | 行数 | 职责 |
|------|------|------|
| `sw_constants.py` | 39 | SW 2025 API 枚举常量（经验证的晚期绑定值），来源：`CAD/SW2025_API_REFERENCE.md` |
| `sw_driver.py` | 901 | COM 驱动封装 — 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存 |
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
- **SetAddToDB 两面性**（`dxf_to_sw_features.py` 实测，两个方向都会静默失败）:
  孔切除草图必须 `_sketch_loop(no_snap=True)`——SetAddToDB 绕过草图推理捕捉，
  否则键槽矩形角部距截面圆边 0.04mm 会被吸附畸变，致 `FeatureCut3` 返回 None；
  **但 boss 草图必须 `no_snap=False`**——SetAddToDB 模式下线端点不自动合并，
  多线环开环导致拉伸失败（八边环实测）

### 已移除的功能（v0.3.0 起不再维护）

PDF/图像矢量化整条链：`convert_pdf.py`（Zhang-Suen 骨架化 PDF→DWG）、
`src/core/vectorization/`、`io/pdf_importer.py`、`io/image_importer.py`。

## 路径与平台注意事项

- 项目路径包含中文字符，在终端中操作时注意编码。
- **控制台重定向日志是 GBK 编码**：脚本 `>` 重定向输出的日志为 GBK（Windows 控制台默认代码页）。日志混有非 GBK 字符（如 ✓）时 `iconv -f GBK -t UTF-8` 会中途失败，改用 `grep -a`（文本模式）直接读原始文件。
- Windows 环境下 PythonOCC 的 `pip install` 容易失败，务必使用 conda-forge 安装。
- SolidWorks 自动化功能仅限 Windows，需要安装 SolidWorks 2025 和 `pywin32`。
- **`convert_dwg_to_3d.py` OCC 懒加载**: OCC 导入已改为延迟加载（`_ensure_occ()`），仅需 DXF 解析时（如 `dxf_to_sldprt.py` 引用 `parse_shaft_from_dxf`）不再依赖 PythonOCC。该脚本本身是**完整可用的**——包含 DXF 几何解析、旋转体建模、键槽布尔减运算、STEP 导出。
- **版本号同步**（发版时全部要改，当前均为 `0.6.18`，已核对一致）:
  `app.py:15` `APP_VERSION` / `main_window.py:28` `setWindowTitle` /
  `main_window.py:535` 关于对话框 / `CLAUDE.md` 本节 / `README.md`（"当前版本"行
  + 路线图段）/ git tag，外加两个转换器脚本横幅（`dxf_to_3d_general.py` 与
  `dxf_to_sw_features.py` 的 docstring 与结尾 print）。
  ⚠️ **tag 落后 HEAD**（2026-09-23 查）：`git describe --tags` =
  `v0.6.18-4-g085589b`——tag 指向 28ae262，之后又有 4 个 v0.6.18 前缀的
  文档/工具提交未纳入标签。要求 tag=HEAD 时需 `git tag -f v0.6.18 HEAD`
  前移后再 push。
- **`.gitignore`**: 自动排除生成的 CAD 输出文件（`*.SLDPRT`, `*.sldprt`, `*.SLDDRW`, `*.step`, `*.stp`, `*.igs`, `*.iges`, `*.svg`, `*.log`）和 CAD 软件锁文件。`CAD/temp_output/` 下的源脚本（`generate_*.py`、验证工具）与测试样本 DXF/DWG 纳入跟踪，仅输出产物被排除。不要将输出文件加入版本控制。
  **迭代产物一律以 `_` 前缀命名**——`.gitignore:85-87` 已落地 `CAD/temp_output/_*`、`/_*.py`、`*.diff` 三条规则（v0.6.16 补齐），`git status` 现已干净，可直接作为提交前检查依据。新建一次性调试脚本/版本备份/diff 时必须带 `_` 前缀，否则会重新污染 `git status`。
  ⚠️ `*.exe` 全局排除：根目录三个安装器（`micromamba.exe`、`Miniconda3-latest`、`Miniforge3-latest`，共约 180MB）因此未入库——它们是环境安装遗留物，不是项目产物。
  ⚠️ **`.gitignore:20` 的 `*.swp`（本意是 vim swap）与 SolidWorks 宏工程文件扩展名撞车**，`soldwork/Macro1.swp`、`Macro2.swp`、`test.swp` 三个 SW 宏工程被静默排除、从未入库。要保留某个 `.swp` 宏工程需显式 `git add -f`，或把该规则收窄为 `.*.swp`。

## Git 约定

- **Commit 消息格式**: `<版本标签>: <简短描述>`，如 `v0.5.0: DXF→SW 全流程打通`
- **Co-Authored-By**: 每次 commit 末尾添加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- **自动推送**: 每次本地 commit 后自动 `git push`（用户偏好设置）
- **每次建模使用新文件名**: SW 模型不能覆盖已有文件（防止 SW 进程占用导致保存失败），使用时间戳确保文件名唯一
- **SW 同时只保留一个模型**: 建模/导入完成后**不要立即关闭**（模型留在 SW 里给用户查看）；下一次重建前先关掉上一个再建新的——防 SW 进程内模型堆积崩溃，同时保住可查看性。⚠️ **代码尚未落地（用户要求先不动）**：`sw_driver.py` 的 `disconnect()` 目前仍是收尾自动关活动文档（会把刚建好的模型也关掉），落地需改收尾逻辑为只关非本次构建的旧文档
