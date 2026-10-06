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
# --from-model：改走新框架 src/rebuild/（图纸→特征树→SW），不经 CSG。
# 旧 CSG 路径仍是默认——新路径的基体轮廓还只有"视图包围盒"一级（见下 [GAP]）
$PY dxf_to_sw_features.py CAD/test_simple/flange_d80.dxf --from-model

# 新框架 src/rebuild/ 验收表（回归入口，与 run_simple_regression.py 平行）
PYTHONIOENCODING=utf-8 $PY run_rebuild_acceptance.py [靶子...]         # OCC 表
PYTHONIOENCODING=utf-8 python run_rebuild_acceptance.py --sw [靶子...] # SW 表（需 SW 2025）

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
# 由 .gitignore 的 `/_*.py`、`CAD/temp_output/_*` 排除，调试完即弃；根目录现存 214 个（2026-10-06
# 计数）分九类：`_probe_*.py` 几何探针（59：_probe_ysec 逐 y 层截面 / _probe_zsec
# 水平截面 / _probe_tor9 挂耳 / _probe_gap145 挂耳间隙）、`_sw_*.py` SW COM API 探测
# （24：2026-09-28 一轮 fillet/planes/cut/edge/circ 探针，`_sw_cleanup.py` 收尾）、
# `_diag_*.py` 根因诊断（14）、`_wx_*.py` 20230425 样本真值建模与诊断（10：`_wx_build.py`
# 手工建模真值 + 8 个 `_wx_diag_*` + `_wx_verify_step` 诊断）、`_d79_*.py` D79307 探针（5：
# `_d79_scan/loops/edgeq/slab/text`）、`_analyze_*`/`_render_*`/`_run_*` 等杂项（22）、
# `_csg_*`/`_bak_*` 代码版本备份（各 3；`_bak_ged/mtd/sv.py` = v0.6.20 出图侧三文件
# 修复前快照）、`_dump_*`/`_draw_*` 截面叠加工具链（见下方"截面叠加图"节）、
# `_yz_*.py` YZYX95.4-20 齿箱上盖（φ220 大件，2026-10-02~06 五轮 70 个）：
# `_yz_build.py` 按图纸逐尺寸手工参数化建模（v15a，fuse/cut 图元拼装 → `_yz_3d.step`，
# 体积 7,782,529.7）。用户读法三轮闭环：①2026-10-05 五缺陷标记（v13 #3 东壁中央
# |y|<50 是槽非墙、v13 #5 孔口 1.5×45° 倒角改直切锥体、v14 #4 缝改 Ø150 r75 沉窝、
# #1/#2 反事实验证定案=顶壁下隧道+侧壁窗口——`_yz_nc_build.py` 删顶壁版评分冲突：
# BL 丢 y=±75 外壁线、TR 丢两条斜肩线）；②2026-10-06「俩段凸起平台、中间圆槽贯通」
# 成立——C—C 是局部剖，浅腔段 (x −51.5..−15.5) 平台 |y| 60..75 悬空 z 60..100（图纸
# 实锤：u=−75 竖线精确从 z=60.00 起、(e) 弧 c=(±80,60) r5 + z=100 细线），v15
# 平台底 12→60（多料 51,840 切除）；v15a 修两处圆角伪影——(b) 工具圆柱须与框同跨
# （旧两端各短 0.1mm 留全截面垫，东垫 v15 悬空后投影 L 形伪边）、(e) 月牙裁掉 r5
# 圆与 R95 裙圆切点 (±76,57) 外的"唇"（|y|≥76 ∧ z≤57，maxd≈2.1）。
# 评分：TL 缺0/多49、BL 缺0/多50、TR 缺0/多38、TRW 缺106/多31（西半对照不修）、
# DR 缺16（r84.5，图纸 A—A 与 DR 不自洽）/多14（#4 沉窝口缘 r75 弧，图纸不画
# 外缘，DR 不完整模式再现）；TR 38 = 24 pre-existing + 14 条 z=60 平台底边（真实
# 几何、图纸两半全层皆不画，记账保留）；材料探针 27/27（平台下 z=59.9 OUT、
# 垫心/唇点 OUT、月牙 IN）；SW 验收 `_yz_sw_20261006_164832.sldprt`。
# 工具链：`_yz_hlr`（模型 HLR → `_yz_hlr.json`）→ `_yz_match`（评分，THRESH 首参）/
# `_yz_win`·`_yz_layers`（图纸窗口/全层 dump——⚠ 图上 22 层全 off=True；两者用默认
# python）/`_yz_segdump`（HLR JSON 窗口分段）、`_yz_seccheck`（模型截面导出）、
# `_yz_probe_mat`（BRepClass3d 材料探针）、`_yz_rayprobe`（沿轴射线材料区间探针，
# 查遮挡）、`_yz_dump*.py`（图纸实体逐轮 dump 22）、`_yz_sw.py` 导入 SW + 时间戳另存。
# 其中两个常用：
# `_run_rebuild.py` 受控实验/基线重跑（直接调 convert_dxf_to_3d，不经 CLI、不触发
# SW 导入——单靶子重跑首选）、`_sw_show.py` 把 STEP 导入 SW 留给用户看（不调
# disconnect()，绕开"收尾关活动文档"问题）。
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
# ⚠️ input.step 必须是**原始 STEP**（SW 导出 / 基准模型），**不要喂闭环重建产物**：
#   重建模型带被布尔裁剪过的 B 样条/球面，精确 HLR 对它们**静默返回空**（不是报错、
#   不是空文件——只是那个方向少几条线）。实测轴测量_3d.step（重建产物）side 视图
#   83 线 → 5 线，剖面图闭环随之从 42,379.88 崩到 1,016,930（视图分离 5 区 → 3 区，
#   top/side 凑不出封闭环）。同一份代码喂 三维/轴测量.STEP 逐位复现 42,379.88。
#   判断法：生成日志里某个视图的线数明显偏少（如 side 5 线）就是它。
#   注：剖面本身走 PolyAlgo（网格）不受影响，所以剖面视图照出——缺的是三视图那一路
$PY model_to_drawing.py input.step out.dxf --no-section   # 只要三视图
$PY dxf_to_3d_general.py out.dxf                         # DXF → 重建 STEP（末尾会尝试导入 SW）
$PY compare_models.py 基准.step 重建.step                # 体积/bbox/布尔差定量对比
# ⚠️ bracket 必须带 --dx 63.56：CSG 系 x=物理x−63.56、z=物理z−22，只给 --dz 会残留
#   63.56mm 的 x 平移（净差不受影响，但多余/缺失/重合三项全失真，见下方口径注）
#   （v0.6.19 起口径由 63.65 改为 63.56——旧值含"坐标归一化"引入的 0.4947mm
#   系统错位，见 docs/CHANGELOG.md v0.6.19；与历史数值对比须认准各自口径）
$PY compare_models.py --dx 63.56 --dz 21.95 基准.step 重建.step  # 平移对齐（重建系→基准系）
$PY compare_models.py --dx 63.56 --dz 21.95 --split -5,0,56.5 基准.step 重建.step  # 逐段拆分多余/缺失
$PY compare_models.py --dx 63.56 --dz 21.95 --split -5,0,56.5 --split-axis x 基准.step 重建.step  # 分段轴换 x/y

# CSG_WELD=1：微边链端点焊接 + 两遍环提取取面积大者（门控写成 `os.environ.get("CSG_WELD")`，
# 分别在 weld_chain_ends 调用处与 _extract_rings_impl 的两遍调用处）。
# HLR 生成的图纸易把外环打成碎段，bracket 基线就是在该开关下取得的——
# 与历史数值对比时必须同环境，否则重建结果不可比
# NO_EXTRAS=1：关闭"整圆附加环"（v0.6.19，挂线穿圆外的整圆合成 36 段弧环
# Union 到棱柱，恢复被外环遍历淘汰的凸台圆）。默认开启；此开关只用于受控实验
# （v4 三视图实测：开 多余 903.16 / 关 1472.04，缺失与净差基本不变）
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
# ⚠️ 该模块的 project_shape_to_2d / _dedup_lines 被 model_to_drawing.py 复用
#   （HLR 投影的唯一实现），改这两个函数会同时影响两条出图路径。2026-10-01 修两处：
#   ① `_dedup_lines` 丢弃**退化线段**（两端重合）：曲线离散在驻点处会吐出这种零长
#      LINE，画不出东西却是图纸里的非法实体（选不中/删不掉）。D79307 三视图 8 条、
#      IMU 5 条、轴测量 2 条
#   ② 可见优先：HLR 会把**同一条棱同时塞进 VCompound 与 HCompound**（D79307 主视图
#      160 条可见里 42 条也出现在隐藏集，26%；30 条来自 HLR、12 条来自
#      _supplement_outline_lines）。隐藏线后画 → 把黑轮廓整片盖成蓝色（渲染实测
#      主视图 35,595 蓝像素 vs 1,765 黑像素，等于整张图看不见可见轮廓）。现在按
#      0.001mm 细键跨层比对，可见优先。注意**同层**去重（_dedup_lines）用 0.1mm 键、
#      **跨层**比对用 0.001mm 键——混用会把真实短段吞掉
#   判别图有没有这毛病：`_probe_layerlen.py <dxf>` 看某视图带的可见/隐藏总长，
#   或直接渲染数像素。修完 D79307 主视图 19,507 黑 / 15,306 蓝
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

实际存在的三个解释器（2026-09-28 复测，PyQt6/pytest 仍三者皆无；选错解释器是最常见的时间浪费）：

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

src/rebuild/ (新框架——图纸理解与三维重建的重写，✅ 阶段 0~4 落地，见下方专节)
  model/ ← evidence/ ← views/ ← conventions/ ← features/ ← verify/（单向依赖）
  emit/ = 旁支，只依赖 model（occ_builder / sw_builder 两个独立发射器）
  pipeline.py = 唯一入口；selftest.py / inspect.py / report.py / verify_legacy.py = 仪器

src/utils/ (工具模块：配置管理、日志、线程工作器、单位换算)
resources/styles/ (QSS 主题：light_theme.qss / dark_theme.qss)

根目录独立脚本（不通过 main.py 调用，直接命令行运行）:
  dxf_to_sldprt.py       — DXF 阶梯轴 → SW .sldprt 原生文件（DXF 解析 + SW COM）
  dxf_to_3d_general.py   — 通用 DXF 工程图 → 3D STEP + SW .sldprt（任意零件图，9821 行）
                           核心链: 边图构建→封闭环检测→视图分离(Y+X 间隙，v0.6.15 起含剖面行识别)
                           →CSG 体积求交 / 单视图轮廓拉伸
                           CSG: 各视图外轮廓拉伸为棱柱→布尔交集→内部特征布尔减(P0)→投影验证(P1)
                           →注解驱动分析(P2，中心线对称 + HATCH 剖面验证)，全部自动执行
                           v0.6.15: 剖面视图识别——剖面行打标 _is_section、父视图匹配、
                           全环枚举（外环−内环）建带孔截面 face 沿父轴向拉伸为剖面棱柱
                           与标准棱柱求交（只会删假材料不会加）；P0/注解消费端全部加
                           _is_section 守卫
                           命令行: --single-view 强制轮廓拉伸 / --multi-view 强制包围盒
                           v0.6.19: 删除"坐标归一化"（旧 Fix 1，曾把所有模型 bbox 中心
                           强移到原点 → bracket 0.4947mm 系统错位 = 用户标记的凸台右弧
                           空缺）；新增"整圆附加环"（挂线穿圆外的整圆 Union 回棱柱，
                           恢复被外环遍历淘汰的凸台圆；NO_EXTRAS=1 可关，受控实验用）
                           v0.6.20: "隐藏斜断面刀"（_hidden_slant_cuts）——不可见斜切
                           内腔（图纸只用隐藏**斜线**表达，旧版在 _is_skip_entity 处
                           整条丢弃）。两条证据缺一不出刀：top 外环内隐藏斜线弦 + 该弦
                           x 跨度映射到 front 帧内的隐藏水平线（给 z）。区域 = 外环被
                           弦切成两半中 x 跨度 ⊆ 弦 x 跨度者；两半都合格/都不合格 →
                           多义跳过。轴测量靶子由此从 +1,920 变 0 差（SLANT_DBG /
                           SLANT_DBG2 为诊断打印开关）
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
                           2026-10-01（D79307 出图）三处：
                           · `_clamp_axis_pos`：候选剖面位置的轴坐标**必须夹进该圆柱面自身
                             bbox 跨度**——`gp_Cylinder.Axis().Location()` 是无限轴上的
                             任意点，实测 r12.39 那条轴落在 (21, 350, −37.08)（零件
                             Z∈[−35.1, 4.9]），照搬就得到整片在零件外的"横剖"，剖空
                           · 空剖面守卫（在 model_to_drawing）：实测截面面积 0 的剖面丢弃后
                             按 SECTION_LABELS 重排编号。**判据取 OCC 实测面积，不能取
                             2D 路径面积**——路径缺失时两者同为 0，自检会判 [OK]
                           · project_section_poly **不再输出隐藏线**（键保留空列表）：
                             剖视图按制图法不画虚线；且 PolyAlgo 的隐藏边是网格碎段
                             （D79307 A—A：1270 条 / 238.5mm，均值 0.19mm），画上去只是
                             把黑轮廓涂蓝。闭环那头也不受影响——HIDDEN 线型命中
                             `dxf_to_3d_general.SKIP_LINETYPES` 本来就跳过
                             （实测去掉后 剖面图闭环 42,379.87674077447 逐位不变）
                           可见线仍要按 0.001mm 键去重（PolyAlgo 同一条棱同时进
                           VCompound 与 OutLineVCompound）
  dxf_to_sw_features.py  — 通用 DXF 工程图 → SW 原生特征模型（1111 行，v0.6.6 新）。复用
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
| `docs/` | `CHANGELOG.md` — v0.5.4~v0.6.20 逐版本根因叙事，三段倒序（主线 v0.6.11~v0.6.20 / dxf_to_3d_general 精度收敛链 v0.5.4~v0.6.10 / dxf_to_sw_features v0.6.6~v0.6.7）。查"某阈值为何是 0.1"这类历史依据时看它 |
| `.claude/` | `settings.local.json` — 预授权的 Bash 权限列表；`skills/` — 项目级启用的技能符号链接 |
| `.agents/skills/` | 4 个技能：`mechanical-engineer`、`solidworks-cad`（泵叶轮参数化）、`python-code-review`（含 5 个参考文件）、`python-packaging`；仅前两个经符号链接在项目级启用。根目录 `skills-lock.json` 锁定 `mechanical-engineer` 来源 |
| `CAD/` | 51 个 VBA 宏 `.bas`（本目录 24 含 VerifySW2025_v33~v45 验证系列 + `verify_log/` 27 个早期迭代；另 4 个在仓库根 `soldwork/`），全部入库、`SW2025_API_REFERENCE.md`、测试样本 DXF/DWG（`20160112` 阶梯轴、`reducer`、`法兰练习`、`图形练习`、`20230425-160012-85913` 尼龙王 φ19×100 + 夹紧环 φ60×30——PDF 矢量化来源：线条双线、圆弧打成 LWPOLYLINE 折线（2138 条）、0 文字标注，解析须读折线顶点；`YZYX95.4-20齿箱上盖零件图.dwg`（φ220 大件靶子，与 D79307 无关；2026-10-06 手工参数化重建 v15a——用户读法三轮闭环（v13/v14 五缺陷标记 + v15「俩段凸起平台」浅腔平台底 12→60 + v15a 两处圆角伪影修复），转换副本 `CAD/temp_output/_yz.dxf`，建模脚本根目录 `_yz_build.py`，相关脚本见 `_` 脚本节 `_yz_*` 族）；`_wx_build.py`（gitignored）是按图手工建模的真值参照）、`temp_output/` 闭环验证链工作区（图纸 DXF 迭代样本——`bracket_angker_三视图_v4.dxf` 与 `bracket_angker_图纸_20260922_剖面图.dxf` 是当前两个 bracket 基线、`spoon_三视图.dxf`、`pf60k_闭环_三视图_20260817.dxf`、`D79307A264FCA6D8EC32E95B1B11BDBD.dxf`/`IMU.dxf`/`轴测量.dxf`（各配 `_剖面图.dxf`；轴测量是唯一 100% 覆盖靶子）、`generate_engineering_drawing.py` 等验证工具，源文件入库、输出产物 gitignored）、`test_simple/` 简单用例 |
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

版本 v0.6.20（git tag 为准）。代码内三处版本字符串（`app.py:15` /
`main_window.py:28` / `main_window.py:535`）、README 与两个转换器脚本横幅
已于 2026-10-02 统一 bump（此前 4 个 `v0.6.20:` 提交先落地、版本簿记后收口，
tag 曾落后 HEAD 16 个提交，见下方"版本号同步"）。
**逐版本根因叙事已迁至 `docs/CHANGELOG.md`**（v0.5.4~v0.6.20）——
本节只留仍在影响决策的部分。

### 当前精度断点

| 靶子 | 重建 vs 基准 | 状态 |
|------|-------------|------|
| PF60K 法兰盘（CSG，`CSG_WELD=1`） | 263,119.41 / 261,935（+0.45%） | 收敛（v0.6.15 起的真基线，逐位可复现；此前本表记的 261,726 是 v0.6.10 旧值未同步） |
| PF60K 法兰盘（SW 特征模型，18 特征） | 261,875 / 261,935（−0.02%） | 收敛 |
| bracket angker（三视图） | 净差 +539.61（+0.28%），重合 **99.5%**（多余 903.16 / 缺失 935.28） | 收敛；**v0.6.19 删除"坐标归一化"**（dx 口径 63.65→63.56）：多余 2,898.96→**903.16**、缺失 2,356.21→**935.28**、重合 98.8%→**99.5%**——用户标记的"凸台右弧空缺"即该块引入的 0.4947mm 系统错位（盒内材料 32.9→25.0，基准 32.5）。v0.6.18 刀组修复连带改善（恢复被多切的弧端/球台/弦棱 → 比 v0.6.17 多留 252）。**2026-09-24 挂耳间隙修复后净差从 −267.38 变 +538.38 是修复的必然效应**（挂耳右半实心恢复 +805.6 的缺失减少，见下行；非回归）。遗留：挂耳左半盒外多余 ~457（修复前就有的旧问题，修复后微减至 456.9，基准左半无材料） |
| bracket angker（三视图+剖面图纸） | 净差 +8,114.06（+4.23%），重合 **99.6%**（多余 8,183.39 / 缺失 698.10） | **v0.6.19 删除"坐标归一化"**（dx 口径 63.65→63.56）：多余 8,946.99→**8,183.39**、缺失 1,638.74→**698.10**、重合 99.1%→**99.6%**（净差本身是 +4.23% 的臂区方块 + 融合投影天花板，见本行末段）。用户三缺陷已修复（端头弧/薄壁/挂耳五保护体；净 +202.7 = 修复净加材料效应非回归）。**2026-09-24 用户两处挂耳间隙缺陷（基准(163.08,−9.42,26.09)/(164.80,7.90,23.96)）根因+修复**：`_tor9` 臂环盘 revolve 保护体三错——①轴边画在旋转轴上 MakeRevol 退化生成 53.7% 空心体（顶底圆盘丢、torus 外圈丢）→ 外带反刀（盒−残壳）把正体挂耳芯挖空+外圈切光；②直段画在管心 r9 应为外轮廓 r12；③弧 θ∈[π/2,3π/2] 经 (6,7) 是内轮廓，外轮廓应 θ∈[0,π/2] 经 (12,7)。修复 = ε=0.001 离轴边 + 外轮廓 wire → 实心 100.00%（体积 8,772.80 = 理论 8,772.58）；右半挂耳恢复（107.4→272.0 vs 基准 278.0、0.1→53.3 vs 58.4），净差 +805.0 = 缺失恢复的必然效应。**剩余误差已定位成一块**（2026-09-22 截面叠加图 + 盒探针）：臂区方块 x[96,162]×y[±25] z>27 存活——探针 z[27,33] 重建 2,382.3 vs 基准 1,772.7、z[38,42] 1,588.2 vs 1,181.8，而同区域三视图路径 1,770.1 / 1,180.1 精确。**v0.6.18 证明 `sec_B`/`sec_C` 部分剖面棱柱不可行**：剖面只携带剖切位置零厚度截面信息（B—B 截面 = 两片 9.8×44 壁 862.4，逐 SOLID 探针已证出图侧截面提取正确、无 bug），而管腔沿 x 处处渐变（x[96,106] 实心条 → x[122,128] 中空壁 → x[128,144] 渐实心），图纸不含窗口信号（剖切线只有箭头无贯通线）——任何窗口的全长拉伸都误裁真材料（实测 HATCH 兜底 Fuse 合并后净差 −68.93%）。门控"非全尺寸跳过"即正确行为：HATCH 兜底加面积门控（材料面积 <90% 父 bbox → 跳过），实际只有 `sec_A`(y=0) 生效 |
| 轴测量（L 形底 + r20 半圆槽 + 三角楔形槽，`CSG_WELD=1`） | 42,380.18 / 42,380.18，**多余 0.00 / 缺失 0.00 / 重合 100.0%** | 完美吻合（v0.6.20）。图纸在 `CAD/temp_output/轴测量.dxf`（+ 剖面图版），基准 `三维/轴测量.STEP`，对比须 `--dx 20 --dy 22`（重建居中系）。**v0.6.20 前管线读不出三角楔形槽**（+1,920，只由隐藏斜线表达）——「隐藏斜断面刀」补上该词汇表后归零。剖面图纸路径 42,379.88（缺失 0.30 = 剖面路径固有差，与斜断面无关，覆盖同样 100.0%） |
| 简单模型回归套件 | 6/6 | 绿 |

基准模型在 `三维/`（gitignored，用户私有数据）。bracket 与历史数值对比
必须在 `CSG_WELD=1` 下进行，否则不可比。**跨版本可比的只有"净差"一列**——
早期记录里的"多余 8,836 / 缺失 1,730"是 `--split` 逐段拆分口径，与全量口径
不可直接比较。

⚠️ **口径更正（2026-09-22 全流程重跑发现）**：曾记录的"全量口径 11 万级"
（三视图 112,507.67 / 112,774.01、剖面图纸 118,396.50 / 111,088.01）**是错的**——
那批数是在 `--dz 21.95`、**漏了 `--dx`** 的情况下量的，混合了 63mm 级的
x 平移伪影。补上 dx 后同一对模型是：三视图 多余 1,681.28 / 缺失 1,952.90 /
**重合 99.0%**，剖面图纸 多余 8,946.99 / 缺失 1,638.74 / **重合 99.1%**
（此组为**旧代码 × dx 63.65**）。
净差不受影响（平移保体积），历史"净差"一列仍有效；受影响的只有多余/缺失/重合。
教训：这三项对平移极敏感，报数前先确认对齐，别用净差"看起来对"来反推对齐正确。

⚠️ **第二次口径变化（v0.6.19）**：删除"坐标归一化"后重建模型少了 0.4947mm 的
系统错位，**dx 最优值由 63.65 变为 63.56**；同一对模型（新代码 × dx 63.56）：
三视图 多余 903.16 / 缺失 935.28 / **重合 99.5%**，剖面图纸 多余 8,183.39 /
缺失 698.10 / **重合 99.6%**。**跨版本比较"多余/缺失/重合"必须连口径一起对齐**
（旧值配 63.65、新值配 63.56），混用会把口径差算成代码差。

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
`# TODO`，OCC API 调用已注释在代码中：

- `gui/view3d/`（`display_shape`/`erase_all`/`fit_all` 已定义，等 `OCC.Display.qtDisplay`）
- `core/projection/`（`HLRProjector`/`Orthographic`/`Axonometric`/`SectionView`，等 `HlrAlgo_Projector`）
- `core/io/`（8 个导入/导出器；`FormatRegistry` 已完整，GUI 导入菜单已接
  `DxfImporter` 但当前返回空 Document）
- `core/annotation/`（`AutoDimension`）

⚠️ **GUI 骨架与根目录脚本是两套独立实现**：三视图投影、2D→3D 重建这些能力
在根目录脚本里已生产可用，`src/` 里的同名模块是尚未接线的另一份。改算法请
落在根目录脚本，不要误以为 `src/core/projection/` 是现役代码。
（**`src/rebuild/` 是第三份，也是唯一在往前走的**：新框架，判据是"特征+尺寸"
而不是几何交集；旧管线的精度收敛已到信息论天花板，新工作应该落在 `src/rebuild/`）

⚠️ **`src/core/reconstruction/` 已判定过时，不再续写**（2026-09-28）：
`WireMaker`/`FaceBuilder`/`ExtrudeBuilder`/`RevolveBuilder` 的分解是**几何优先**
思维（假定"先有线面、再有零件"），与 `docs/ARCHITECTURE.md` 定下的新框架入口
（先有依据和 Claim）冲突。**不要去填它的 `# TODO`**，它应由 `src/rebuild/` 取代，
最终删除。

### 新框架 `src/rebuild/`（设计见 `docs/ARCHITECTURE.md`）

图纸理解与三维重建的**重写**框架——不与 `dxf_to_3d_general.py` 共享代码。
核心是换中间表示：**几何进几何出 → 经过"特征+尺寸"的符号层**。

三条核心原则（`ARCHITECTURE.md` §3）：
1. **系统里不存在裸数值**——每个数字都是 `Claim`（值+依据+方法+置信度+备选）。
   由此"知道拒绝"塌缩成对 Claim 的查询，不是外加模块
2. **歧义不提前消解**——"圆是孔还是凸台"在俯视图里同形，保留两个假设让约束剪枝
3. **仪器先于引擎**——验证器先于重建器；阶段 0 刻意把验证器指向旧管线

分层与依赖方向（单向，`ARCHITECTURE.md` §5）：
`model`（零依赖纯数据）← `evidence` ← `views` ← `conventions` ← `features` ← `verify`；
`verify` **不得依赖 `emit`**（验证须能只看特征树就预测形状）。

解释器分层：`model`~`features` + `verify.compare/coverage/gate` + `report` 只需
ezdxf+numpy，**跑默认 python**；`verify/step_probe.py`（读 STEP 量尺寸）与
`emit` 需要 OCC。**`verify/__init__.py` 不许导出 step_probe** —— 导出了就等于
把整包的 import 绑死在 cad-occt 上，selftest 的 E 组会把这条拉回。
阶段 1 的 `verify.reproject` 同样归 OCC 侧。

阶段 0 ~ 4 全部落地（2026-09-28）。`src/rebuild/` 现有：`model/`（Claim/geom/
geom2d/ids/feature_tree/questions）、`evidence/`（dxf_reader/model + text_parser）、
`views/`（view_detector + view_typer + correspondence 跨视图对应）、`conventions/`、
`features/`（recognizer + solver + library + prior）、`verify/`（compare/coverage/
gate/step_probe）、`emit/`（occ_builder + sw_builder）、`report.py`、`inspect.py`、
`rebuild.py`（端到端 CLI）、**`pipeline.py`（唯一入口：`pipeline.rebuild(dxf,
step=|sldprt=|sw=|force=)`）**、`selftest.py`、`verify_legacy.py`。逐阶段叙事与实测数见 `docs/CHANGELOG.md`
顶部「新框架 src/rebuild/」段；`docs/ARCHITECTURE.md` §8 各阶段带 ✅ 状态行。
```bash
python -m src.rebuild.inspect <dxf> [--json|--texts|--dims|--views|--explain HANDLE]
python -m src.rebuild.rebuild <dxf> [--step PATH] [--sldprt PATH|--sw] [--force] [--json]  # 端到端 CLI
python -m src.rebuild.selftest       # 272 项自检（2026-10-01 实测），退出码 0 = 全过（项目无 pytest）
# 拿图纸判一个 STEP（阶段 0 验收入口，**需 cad-occt**；退出码 0/1/2/3 = ACCEPT/REJECT/需确认/出错）
PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
PYTHONIOENCODING=utf-8 $PY -m src.rebuild.verify_legacy <图纸.dxf> <模型.step> [--json]
```
阶段 4 实测（9 个靶子，两张表）：6 个简单靶子里 **4 个体积逐位吻合**（block_3view /
plate_100x60 / flange_d80 / 法兰练习，bbox 差全 0.00；SW 表另核**特征步数 = 特征模型**），
且 OCC 表与 SW 表在这 4 个上逐位相同——两个独立发射器（一 OCC 一 COM，无共享代码）
互为交叉验证。其余 5 行标 `[GAP]`。
⚠️ **`[GAP]` 是已知结构缺口、不是回归**，两条都不在发射器里：
① **基体轮廓目前取视图包围盒**（矩形棱柱）⇒ `l_bracket` / `图形练习` / `bracket`
   体积偏大（+227% / +200% / +130%），真实外轮廓是 L 形 / 台阶 / 回转体；
② **多视图下的回转体识别未做** ⇒ `PF60K`（法兰盘）被按板类零件建（−31%）。
**别为了让表变绿去调发射器**——那会把"没读到"变成"读错了"（体积对了结构全错，
正是本框架要消灭的病）。表上红的地方就是还没读出来的地方，见
`run_rebuild_acceptance.py` 顶部注释。
SW 表比 OCC 表更严：三个大靶子**发射就被拒**（`FeatureCut3` 返回 None），根因
同样是上面两条 —— PF60K 的 7 条同心圆被读成 7 个同轴通孔（第一个 Ø60 切完后
第二个 Ø50 无材料可切，切除不幂等）；bracket 的 r12 圆（GUESS(hole|boss)）圆心
(193.3, ·, 24) 与基体包围盒 x 上界 205.3 **恰好相切**（真身是臂端圆头）。
验收表因此按"框架自己的 gate"判失败性质：`blocking()` 非空 ⇒ `[GAP] 按设计拒绝`
（不计 FAIL、也不洗绿）；**一条阻塞疑问都没有却失败 ⇒ 疑似发射器 bug、计 FAIL**。
另有一条已记账的静默默认：`BOSS/HOLE/POCKET/SLOT` 的 `axial_at` 参数缺省时
两个发射器都按 **0** 起（不是图纸读数），并各打一行 `[emit] 特征 #n（…）没有
axial_at ⇒ 沿轴按 0 起`。实测症状：bracket 基体自 z=2 起而凸台从 z=0 长出，
整车 z 向 bbox 46 而基准 44（`bbox 差 +2.00`）。根因在识别侧（凸台轴向位置没读出来），
不在发射器——发射器已尽力记账。

阶段 0 关键成果：
- **剖面标题的切平面与半径读出来了**。图纸里明写着
  `B—B  横剖 x=121.89（穿 r25.5 孔轴）`，而旧管线 `dxf_to_3d_general.py:618` 的
  正则 `^([A-Z])[-—–]\1$` 要求整串恰好是标签，把带描述的标题整条丢弃——
  **CLAUDE.md 记为"缺"的 B—B 圆心基准，一直在文件里**。
- **验证器可用且指向旧管线**：判据只用图纸+模型（不需要基准），主判据是
  **尺度无关比例**（图纸可能缩比）。实测 spoon REJECT（Y 偏离 92.3%、
  逐轴比例尺 0.985/0.076/1.000 ⇒ 一句话点名旧管线的强制拉伸），bracket 三视图与
  剖面图纸 ACCEPT（隐含比例尺 1.0016）。
- **验收③ 修正**：6 个回归用例里只有 `block_3view` 具三视图 ⇒ ACCEPT；其余 5 个是
  单视图零标注的极简 DXF，第三向尺寸**不在图上** ⇒ 正确判决是 NEEDS_CONFIRMATION
  （原写"6/6 ACCEPT"是把靶子当成真图纸了，见 `docs/ARCHITECTURE.md` §8 阶段 0）。
阶段 1 ~ 3 各留一条关键成果（细节见 `docs/CHANGELOG.md`）：
- **阶段 1（跨视图对应）**：剖面标题 → 3D 轴线。`x=121.89（穿 r25.5 孔轴）`
  这种**带描述的**剖面标题读得出来（旧管线只认整串恰好是标签的 `^([A-Z])[-—–]\1$`，
  把带描述的一条整条丢弃）；bracket 两条剖面读通并报出坐标系镜像。
- **阶段 2（制图约定）**：8 条约定 + 断裂视图识别，打通了视图坐标系。
- **阶段 3（特征层）**：`R8.5` 首次被读出来（旧管线把 `R8_5` 当 `R8` 读，
  即信息论局限表里那条"R8 vs R8.5 凹槽半径差"在新框架里有解了）。


### SolidWorks 自动化模块 (`src/core/sw_automation/`)

| 文件 | 行数 | 职责 |
|------|------|------|
| `sw_constants.py` | 45 | SW 2025 API 枚举常量（经验证的晚期绑定值），来源：`CAD/SW2025_API_REFERENCE.md` |
| `sw_driver.py` | 912 | COM 驱动封装 — 连接/断开/新建零件/草图/特征/倒角/圆角/键槽/保存 |
| `sw_shaft_builder.py` | 1063 | 阶梯轴参数化建模 — 旋转基体 → VBScript（倒角+圆角）→ Python COM 键槽 |

**SW 模块依赖**: `pywin32>=306` (Windows only)，通过 `win32com.client.Dispatch("SldWorks.Application")` 晚期绑定驱动 SW 2025。

**关键 API 注意**（来源：45 轮 VBA 验证 + Python COM 调试，详见源文件注释）:
- **单位约定**: 所有 SW API 参数使用**米 (meters)**，调用方负责 `mm / 1000` 转换。SW 内部单位设为 MMGS (毫米-克-秒)。**例外**：`SelectByID2` 使用**文档单位（MMGS 下为 mm）**。
- `FeatureFillet3` 的 `Options` 参数在 SW2025 中必须为 `195`（`0` 和 `1` 均静默失败）
- `SelectByID2` Type 大小写：中文 SW2025 中必须用 `"Edge"`（PascalCase），`"EDGE"` 全大写失败；`"FACE"`/`"PLANE"` 大小写不敏感
- `InsertFeatureChamfer` Type=1（角度-距离）参数顺序：`Width=角度(弧度)`, `OtherDist=倒角距离(m)`
  （2026-09-28 复核更正：本节此前写作"Width=距离/OtherDist=角度"，与 `CAD/SW2025_API_REFERENCE.md:267`
  的权威表相反；后者是 45 轮 VBA 验证的来源，且 `CAD/VerifySW2025_v45.bas:173` 的通过用例
  正是 `(1, 1, 0.785, 0.0015, …)` = 45° × 1.5mm。`sw_driver.feature_chamfer_edge` 的实参顺序
  与之一致，无需改。**尚未做"造件量体积"的独立实测**，若日后有倒角进特征树，按体积复核一次）
- VBA 晚期绑定下 `On Error Resume Next` 会导致**假阳性**——每次调用前必须 `Set var = Nothing`
- **VBScript 编码**: 必须使用 **GBK** (cscript 使用系统 ANSI 代码页 CP936)，UTF-8-BOM 会导致编译错误
- **混合架构**: 旋转基体（Python COM）+ 倒角/圆角（VBScript 直接 COM）+ 键槽（Python COM FeatureCut3），各自使用最可靠的接口
- **COM None 编组**: 需要 IDispatch* 参数处使用 `NULL_DISPATCH` / `_null_dispatch()` 而非 Python `None`
- **晚期绑定下"属性 vs 方法"靠 `.Name` 认**（`emit/sw_builder._sw_member`）：win32com 的
  动态对象**永远 `callable()`**，`hasattr(x,"Name")` 才是分界。属性（加括号就
  `'NoneType' object is not callable`）：`GetDocuments`、`GetSketchSegments`、
  `GetActiveSketch2`、`ActiveDoc`、`FirstFeature`、`GetTitle`、`GetSaveFlag`；
  方法：`InsertRefPlane`、`FeatureCut3`。踩一次是半小时
- **负偏移基准面静默落到 0**：`InsertRefPlane(8, −d)` 不报错、把面建在 0 位上
  （实测：孔全切在错误高度）。正解 = **正距离 + 翻转位 `264`**（`8 + swRefPlaneOffsetFlip 256`；
  128 是"中面"、用了会失败）
- **切失败会留下开着的草图 → 后续切除连环失败**：`InsertSketch2(True)` 是**开关**，
  特征建失败时草图仍开着，下一次 `start_sketch` 反而把它关掉。`sw_builder` 的对策是
  `_dangling_sketch` / `_start_sketch` / `_require(driver, …)`——每个切除**必须**校验返回值
- **切除不幂等**：对已经切掉的孔再切一次 → `FeatureCut3` 返回 `None`、整个构建失败。
  这就是 `flange_d80` / `法兰练习` 早先发射失败的根因（阵列与 IR 特征建在同一处）；
  正解是 `pattern_plan` 的覆盖语义（**IR 里已有的实例不重复发射**）
- **`GetPartBox(True)`** 返回 `[xmin,ymin,zmin,xmax,ymax,zmax]`，单位米（不传 True 是米的
  文档单位口径）；**空零件返回全 0**，且**基准面不算在内**——拿它当"有没有材料"的判据要小心
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
- **版本号同步**（发版时全部要改，当前均为 `0.6.20`，已核对一致）:
  `app.py:15` `APP_VERSION` / `main_window.py:28` `setWindowTitle` /
  `main_window.py:535` 关于对话框 / `CLAUDE.md` 本节 / `README.md`（"当前版本"行
  + 路线图段）/ git tag，外加两个转换器脚本横幅（`dxf_to_3d_general.py` 与
  `dxf_to_sw_features.py` 的 docstring 与结尾 print）。
  （2026-10-02：v0.6.20 曾"先提交、后收口"——4 个 `v0.6.20:` 前缀提交落地时
  版本字符串仍写 0.6.19、tag 落后 HEAD 16 个提交（`v0.6.19-16-g99c832c` =
  12 个 v0.6.19 前缀 + 4 个 v0.6.20 前缀）；当日统一 bump 到 v0.6.20 并打
  tag `v0.6.20`，CHANGELOG/README 叙事随之补齐）
  （2026-10-06 复核：tag 又落后 HEAD 3 个提交——`v0.6.20-3-g4716081`，即
  440b543/8fe9712/4716081 三个 YZYX 入账提交，均为 v0.6.20 前缀；内容已在
  正文 `_yz_*` 节入账，仅 tag 簿记待下次发版收口）
- **`.gitignore`**: 自动排除生成的 CAD 输出文件（`*.SLDPRT`, `*.sldprt`, `*.SLDDRW`, `*.step`, `*.stp`, `*.igs`, `*.iges`, `*.svg`, `*.log`）和 CAD 软件锁文件。`CAD/temp_output/` 下的源脚本（`generate_*.py`、验证工具）与测试样本 DXF/DWG 纳入跟踪，仅输出产物被排除。不要将输出文件加入版本控制。
  **迭代产物一律以 `_` 前缀命名**——`.gitignore:85-87` 已落地 `CAD/temp_output/_*`、`/_*.py`、`*.diff` 三条规则（v0.6.16 补齐），`git status` 现已干净，可直接作为提交前检查依据。新建一次性调试脚本/版本备份/diff 时必须带 `_` 前缀，否则会重新污染 `git status`。
  ⚠️ `*.exe` 全局排除：根目录三个安装器（`micromamba.exe`、`Miniconda3-latest`、`Miniforge3-latest`，共约 180MB）因此未入库——它们是环境安装遗留物，不是项目产物。
  ⚠️ **`.gitignore:20` 的 `*.swp`（本意是 vim swap）与 SolidWorks 宏工程文件扩展名撞车**，`soldwork/Macro1.swp`、`Macro2.swp`、`test.swp` 三个 SW 宏工程被静默排除、从未入库。要保留某个 `.swp` 宏工程需显式 `git add -f`，或把该规则收窄为 `.*.swp`。
  ⚠️ **入库产物与脚本脱节（2026-09-25 查，待处理）**：跟踪的 `CAD/temp_output/motor_engineering.dxf` 只有 380 个实体，而 `generate_engineering_drawing.py` 当前产出 1581 个（LINE 1562 / TEXT 14 / CIRCLE 2 / LWPOLYLINE 3）——该产物自入库后未随脚本更新。刷新它可以对齐，但会带来约 3 万行 handle/GUID churn，故 v0.6.19 未动；要刷新就单起一个"仅刷新产物"的提交，别混进功能修复。

## Git 约定

- **Commit 消息格式**: `<版本标签>: <简短描述>`，如 `v0.5.0: DXF→SW 全流程打通`
- **Co-Authored-By**: 每次 commit 末尾添加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`（2026-09-29 更正：近 5 次提交实际署名均为 Claude Code，旧写 Claude 与现实践不符）
- **自动推送**: 每次本地 commit 后自动 `git push`（用户偏好设置）
- **每次建模使用新文件名**: SW 模型不能覆盖已有文件（防止 SW 进程占用导致保存失败），使用时间戳确保文件名唯一
- **SW 同时只保留一个模型**: 建模/导入完成后**不要立即关闭**（模型留在 SW 里给用户查看）；下一次重建前先关掉上一个再建新的——防 SW 进程内模型堆积崩溃，同时保住可查看性。⚠️ **代码尚未落地（用户要求先不动）**：`sw_driver.py` 的 `disconnect()` 目前仍是收尾自动关活动文档（会把刚建好的模型也关掉），落地需改收尾逻辑为只关非本次构建的旧文档
