# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- 最后同步：2026-10-16 事实复核（正文已含 v0.6.26~v0.6.31 内容；tag 仍 v0.6.25，
     簿记见"版本号同步"节）。本轮复核修正：ruff 基线 150→155（新增 F822×1）、
     selftest 421→431、根目录 `_*.py` 计数 418→444、sw_constants.py 行数 45→55、
     代码内版本字符串路径补 `src/` 前缀；其余声明（环境表/PyQt6 缺失、51 个 .bas、
     tests/ 空、脚本行数、gitignore 行号）逐项实测无误 -->

## 项目概述

机械三维二维图互转 — 基于 PyQt6 + OpenCASCADE (PythonOCC) 的桌面 CAD 工具，实现 3D 模型 ↔ 2D 工程图的双向互转。

## 常用命令

```bash
# 启动 GUI 应用（完整 3D 功能需在 cad-occt 环境；无 OCC 时优雅降级为占位视图）
# ⚠️ 实测 2026-08-20：三个环境均未安装 PyQt6，GUI 当前无法启动（需先 pip install PyQt6）。
#    日常开发走下方独立脚本，不经 GUI——GUI 侧核心算法仍是骨架
python main.py

# 代码质量（ruff 只装在 PATH 默认 python 里，两个记录环境都没有）
ruff check src/            # 已知基线 155 告警（2026-10-16 复测）：F401×77 / F541×46 / F821×15
                           # / E741×9 / F841×6 / E402×1 / F822×1
ruff format src/           # 无 pyproject.toml，全部走 ruff 默认规则

# 测试：tests/ 仅 __init__.py，且三个环境均未装 pytest。
# 本项目的真实回归入口是下方 run_simple_regression.py（几何验收），不是 pytest
pytest tests/

# ---- 根目录独立脚本（不通过 main.py，直接命令行运行） ----
# 凡 import OCC 的脚本都必须用 $PY（cad-occt 环境），下同
PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
# ⚠️ 只要脚本可能走到 numpy.linalg（如 ezdxf 读含**拟合点 SPLINE** 的 DXF），
#   必须把 Library/bin 加进 PATH，否则调用瞬间以 Windows 0xc06d007f 致命异常
#   **静默杀进程**（MKL 的 LAPACK DLL 延迟加载失败；见下方"环境安装"节）：
#   PATH=/c/Users/yaoshuo/miniconda3/envs/cad-occt/Library/bin:$PATH $PY xxx.py

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
# 旧 CSG 路径仍是默认；新路径经阶段 5~7（轮廓环/回转体/高度分解）已验收 9 绿，
# 是否切换默认未定
$PY dxf_to_sw_features.py CAD/test_simple/flange_d80.dxf --from-model

# 新框架 src/rebuild/ 验收表（回归入口，与 run_simple_regression.py 平行）
# 2026-10-11 验证制度化起：OCC 表体积/bbox 超容差（0.5%/1mm）判 [RED]，
# bracket 两条附缺陷盒·点断言（PROBES 表）自动复核历史缺陷
PYTHONIOENCODING=utf-8 $PY run_rebuild_acceptance.py [靶子...]         # OCC 表
PYTHONIOENCODING=utf-8 python run_rebuild_acceptance.py --sw [靶子...] # SW 表（需 SW 2025）

# YZYX 齿箱上盖无基准定量验收三件套（27 点材料探针 + 五视图 HLR 投影评分，
# 基线 TL 缺0/多49、BL 缺0/多50、TR 缺0/多38，判红=比 v15a 基线更差）
# --frame auto（默认）按 bbox 自动识别零件系/图纸系（yz_frame.py，2026-10-13）——
# 新框架 src/rebuild 模型在图纸系，直接可评，不必手工转换
PYTHONIOENCODING=utf-8 $PY yz_accept.py [stepfile] [thresh_mm] [--frame auto|part|fw]
$PY yz_frame.py in.step [out.step] [--to part|fw]   # 独立坐标系转换器

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
# 由 .gitignore 的 `/_*.py`、`CAD/temp_output/_*` 排除，调试完即弃（根目录现存 444 个
# `_*.py` + 19 个 `_*.log`，2026-10-16 计数，分十类：_probe 几何探针（含
# _probe_yz_* 齿箱上盖 / _probe_sw_e* SW 发射器）/ _sw SW COM API 探测 / _diag 根因诊断 /
# _wx 样本真值 / _d79 D79307 探针 / _yz 齿箱上盖 / _dump+_draw 截面叠加工具链 /
# _csg+_bak 版本备份 / _z7+_z8+_z9 阶段 7 高度分解/圆角/侧通道调试 / 杂项）。
# `_yz_*.py` YZYX95.4-20 齿箱上盖（φ220 大件，2026-10-02~06 五轮 70 个，v15a 体积
# 7,782,529.7）：建模脚本 `_yz_build.py`，五轮闭环、评分与工具链全貌见记忆
# yzyx-gearbox-cover-drawing（索引已含要点，召回可读全文）。
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

⚠️ **cad-occt 的 numpy 走 MKL，直接调 `$PY` 时 `Library/bin` 不在 PATH**（没经过
`conda activate`）⇒ **任何 `numpy.linalg` 调用都会以 Windows 致命异常 0xc06d007f
静默杀进程**（无 faulthandler 时连回溯都没有）：MKL 的 DLL 是**延迟加载**的，
加载与 IPC 经由 `Library/bin`，PATH 里没有就解析失败；`np.dot`/OCC 几何不走
LAPACK 所以一直没暴露。实测触发路径：ezdxf 读**拟合点 SPLINE**（`ctrl=0, fit≠0`）
必做插值拟合 → `np.linalg.solve` → 崩——YZYX `_yz.dxf` 是第一个这样的靶子
（`8A9/8AC/8AD` 三条 SPLINE，2026-10-12）。修法：跑之前
`export PATH=/c/Users/yaoshuo/miniconda3/envs/cad-occt/Library/bin:$PATH`。

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
                           v0.6.15: 剖面视图识别（剖面行 _is_section 打标 + 全环枚举建带孔
                           剖面棱柱，只会删假材料不会加）；v0.6.19: 删除"坐标归一化"、
                           新增"整圆附加环"（NO_EXTRAS=1 可关）；v0.6.20: "隐藏斜断面刀"
                           （_hidden_slant_cuts，不可见斜切内腔，轴测量由此 +1,920 → 0 差）。
                           逐版本根因见 docs/CHANGELOG.md 主线段
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
| `docs/` | `CHANGELOG.md` — v0.5.4~v0.6.22 逐版本根因叙事，倒序四段（新框架 src/rebuild 各阶段 v0.6.19~v0.6.22 在前 / 主线 v0.6.11~v0.6.20 / dxf_to_3d_general 精度收敛链 v0.5.4~v0.6.10 / dxf_to_sw_features v0.6.6~v0.6.7）。查"某阈值为何是 0.1"这类历史依据时看它；`ARCHITECTURE.md` — 新框架设计（§3 三原则、§5 分层、§8 阶段状态）；`ASSESSMENT_20261006.md` — 2026-10-06 转换能力自评（问题分级 A~F + 优先级）——"下一步做什么"看它 |
| `.claude/` | `settings.local.json` — 预授权的 Bash 权限列表；`skills/` — 项目级启用的技能符号链接 |
| `.agents/skills/` | 4 个技能：`mechanical-engineer`、`solidworks-cad`（泵叶轮参数化）、`python-code-review`（含 5 个参考文件）、`python-packaging`；仅前两个经符号链接在项目级启用。根目录 `skills-lock.json` 锁定 `mechanical-engineer` 来源 |
| `CAD/` | 51 个 VBA 宏 `.bas`（本目录 24 含 VerifySW2025_v33~v45 验证系列 + `verify_log/` 27 个早期迭代；另 4 个在仓库根 `soldwork/`），全部入库、`SW2025_API_REFERENCE.md`、测试样本 DXF/DWG（`20160112` 阶梯轴、`reducer`、`法兰练习`、`图形练习`、`20230425-160012-85913` 尼龙王 φ19×100 + 夹紧环 φ60×30——PDF 矢量化来源：线条双线、圆弧打成 LWPOLYLINE 折线（2138 条）、0 文字标注，解析须读折线顶点；`YZYX95.4-20齿箱上盖零件图.dwg`（φ220 大件靶子，与 D79307 无关；2026-10-06 手工参数化重建 v15a——用户读法三轮闭环，转换副本 `CAD/temp_output/_yz.dxf`，建模脚本根目录 `_yz_build.py`；无基准定量验收三件套 `yz_accept.py`（27 点材料探针 + 五视图投影评分，2026-10-11 验证制度化入库；2026-10-13 起经 `yz_frame.py` 零件系↔图纸系自动变换，新框架模型直接可评）；全貌与工具链见记忆 yzyx-gearbox-cover-drawing）；`_wx_build.py`（gitignored）是按图手工建模的真值参照）、`temp_output/` 闭环验证链工作区（图纸 DXF 迭代样本——`bracket_angker_三视图_v4.dxf` 与 `bracket_angker_图纸_20260922_剖面图.dxf` 是当前两个 bracket 基线、`spoon_三视图.dxf`、`pf60k_闭环_三视图_20260817.dxf`、`D79307A264FCA6D8EC32E95B1B11BDBD.dxf`/`IMU.dxf`/`轴测量.dxf`（各配 `_剖面图.dxf`；轴测量是唯一 100% 覆盖靶子）、`generate_engineering_drawing.py` 等验证工具，源文件入库、输出产物 gitignored）、`test_simple/` 简单用例 |
| `PDF/` | 空目录（预留放参考 PDF 文档） |
| `三维/` | 闭环验证参考模型（gitignored）：`麒浚传动_PF60K-14-50-70-M4-L2-12.SLDPRT`、`bracket angker.stp`、`spoon.SLDPRT` / `spoon.STEP`、`勺子/`（勺子参考图 + STEP/STL 副本） |
| `图片/` | 参考图片两张（`电机.PNG`、`齿轮罩.PNG`，2026-10-09 加入）——2026-10-11 起 gitignored（与 `三维/` 同类用户私有参考数据） |
| `soldwork/` | SW VBA 宏工作区：`.bas` 测试宏（入库）+ `.swp` 工程文件（**未入库**，被 `.gitignore` 的 vim-swap 规则误伤，见下方"路径与平台注意事项"） |
| `tools/libredwg/` | LibreDWG Windows 完整发行版 — `dwg2dxf.exe` 等命令行工具 + Python 绑定；`dxf_to_3d_general.py` 遇 .dwg 输入时自动调用转换 |

### 关键设计约定

**验证准则（最重要）**: 转换/修复的验收以实际生成的模型为准——每次修改转换
代码后运行完整 CLI（生成 STEP + SW 时间戳 .sldprt），**不以代码或日志数值吻合
作为成功标准**。判断几何正确性可加载 STEP 用 `GProp_GProps` 体积 /
`BRepAdaptor_Surface` 面类型做定量核对（体积与理论值精确吻合才是真通过）。

**验证制度化（2026-10-11，ASSESSMENT §D）**: 自动指标（体积/bbox/重合率）到
99.5%+ 时局部可见缺陷仍零命中（bracket 三缺陷、YZYX 五处标记全靠目视）——
历史缺陷已转成自动断言，**每次修复的例行检查序列**：

1. `python -m src.rebuild.selftest` — 439 项
2. `PYTHONIOENCODING=utf-8 $PY run_rebuild_acceptance.py` — 9 绿 + 体积/bbox
   阈值判红（0.5%/1mm，仅 expect=="ok"）+ bracket 缺陷盒·点断言（PROBES 表：
   三缺陷盒 + 凸台右弧两盒 + 3 点分类；gold/shift 2026-10-11 定标实测，
   shift=基准min−重建min，三视图/剖面图 y 差 3mm 各自记）
3. 涉 SW 发射改动 → `--sw` 表（特征步数硬判；SW 表不判体积阈值——发射器口径差）
4. 无基准靶子（YZYX）→ `PYTHONIOENCODING=utf-8 $PY yz_accept.py`（27 点材料
   探针 + 五视图投影评分；判红 = 比 v15a 基线更差，缺>0 或 多>基线+10；
   新框架模型直接喂——坐标系按 bbox 自动识别并平移，yz_frame.py）
5. 视觉链（自动指标再绿也不能省）：`_render_dxf.py` 看图 → `_make_viewer.py`
   点选标记 → `_dump_sections.py`（SEC_PLANES 环境变量可覆盖平面）+
   `_draw_sections.py`（**CWD 必须仓库根**，_viz 相对路径）截面叠加 →
   `_probe_boxes.py` 盒定量复核（截面整片伪影必须盒探针复核，防退化假差异）
6. 新缺陷闭环：viewer 标记 → 盒/点定量 → 入 PROBES 表（gold/shift 实测标定）
坑：平移口径 63.56（新框架重建系）≠ 63.65（旧管线，含归一化错位）；OCC 脚本
一律 $PY；识别侧改动导致重建重定位时盒断言会红——重标定即可（特性非故障）。

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

版本 v0.6.25（git tag 为准；tag 落后 HEAD 见"版本号同步"节）。
代码内三处版本字符串（`src/app.py:15` / `src/gui/main_window.py:28` / 同文件 `:535`）、
README 与两个转换器脚本横幅已于 2026-10-12 统一 bump 至 v0.6.25。
**逐版本根因叙事已迁至 `docs/CHANGELOG.md`**（v0.5.4~v0.6.25）——
本节只留仍在影响决策的部分。

### 当前精度断点

| 靶子 | 重建 vs 基准 | 状态 |
|------|-------------|------|
| PF60K 法兰盘（CSG，`CSG_WELD=1`） | 263,119.41 / 261,935（+0.45%） | 收敛（v0.6.15 起的真基线，逐位可复现；此前本表记的 261,726 是 v0.6.10 旧值未同步） |
| PF60K 法兰盘（SW 特征模型，18 特征） | 261,875 / 261,935（−0.02%） | 收敛 |
| PF60K 法兰盘（新框架 `src/rebuild/`，26 特征回转体） | 261,943.9 / 261,935（+0.0034%） | **2026-10-09 阶段 6 转绿；2026-10-12 v0.6.25 残余追平**（OCC 侧：r8 沉孔 +1,005.3＝correspondence `DUP_TOL` 收紧、锥区 −852.5＝锥台 REVOLVE + 4 帽切 + 内腔补偿切；SW 261,776.7（−0.06%）＝发射器口径差 −167.2）。余 +8.9 微项不追；探针 `_probe_pf60k_slabcmp.py`（平移 −42/−192.89/−28.5；多实体基准须先 Fuse，否则布尔静默假零） |
| bracket angker（新框架 `src/rebuild/`，11 特征） | 三视图 191,970.1 / 191,987.84（−0.01%）／剖面图 192,196.5（+0.11%） | **2026-10-10 阶段 7 高度分解 + 圆角/侧通道转绿**（bbox 差全 0.00、实体 1、`blocking()`=0；SW 191,962.3（−0.01%）/ 191,958.1（−0.02%）——v0.6.25 真圆路径后口径差 +1,062→−8，旧值 193,032.3/193,032.8 的 +0.54% 大半是折线近似的账）。与下方旧管线 CSG 两行无关，各自独立记分 |
| bracket angker（三视图） | 净差 +539.61（+0.28%），重合 **99.5%**（多余 903.16 / 缺失 935.28） | 收敛；**v0.6.19 删除"坐标归一化"**（dx 口径 63.65→63.56）：多余 2,898.96→**903.16**、缺失 2,356.21→**935.28**、重合 98.8%→**99.5%**——用户标记的"凸台右弧空缺"即该块引入的 0.4947mm 系统错位（盒内材料 32.9→25.0，基准 32.5）。v0.6.18 刀组修复连带改善（恢复被多切的弧端/球台/弦棱 → 比 v0.6.17 多留 252）。**2026-09-24 挂耳间隙修复后净差从 −267.38 变 +538.38 是修复的必然效应**（挂耳右半实心恢复 +805.6 的缺失减少，见下行；非回归）。遗留：挂耳左半盒外多余 ~457（修复前就有的旧问题，修复后微减至 456.9，基准左半无材料） |
| bracket angker（三视图+剖面图纸） | 净差 +8,114.06（+4.23%），重合 **99.6%**（多余 8,183.39 / 缺失 698.10） | **v0.6.19 删除"坐标归一化"**（dx 口径 63.65→63.56）：多余 8,946.99→**8,183.39**、缺失 1,638.74→**698.10**、重合 99.1%→**99.6%**。用户三缺陷已修复（挂耳间隙根因 = `_tor9` 保护体三错，修复后净差 +805.0 是缺失恢复的必然效应非回归）。**剩余误差已定位成一块**：臂区方块 x[96,162]×y[±25] z>27（剖面图纸特有；同区域三视图路径精确）。**v0.6.18 证明 `sec_B`/`sec_C` 部分剖面棱柱不可行**：剖面只带剖切位置零厚度截面、管腔沿 x 渐变、图纸无窗口信号——任何窗口全长拉伸必误裁真材料；门控"非全尺寸跳过"即正确行为（HATCH 面积 <90% 父 bbox → 跳过），实际只有 `sec_A`(y=0) 生效。逐段根因见 docs/CHANGELOG.md 主线段 |
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
`verify/box_probe.py`（缺陷盒·点断言，2026-10-11 验证制度化）与
`emit` 需要 OCC。**`verify/__init__.py` 不许导出 step_probe / box_probe** —— 导出了就等于
把整包的 import 绑死在 cad-occt 上，selftest 的 E 组会把这条拉回。
阶段 1 的 `verify.reproject` 同样归 OCC 侧。

阶段 0 ~ 4 全部落地（2026-09-28），**阶段 5（轮廓环 + 锥化）2026-10-07 落地**，
**阶段 6（多视图回转体识别）2026-10-09 落地**（`features/revolve.py`：同轴圆簇 +
剖面轴扫读母线 ⇒ REVOLVE 基体；方料段按"外轮廓 − 回转外径圆"的月牙补料）。
**阶段 7（高度分解 + 圆角/侧通道 + 帧镜像裁决）2026-10-10 落地**——
`features/height_zones.py`（俯视圆分区[轴共线分组+半径序奇偶定角色+切线核实]
× 侧视剪影上下包络取 min/max ⇒ 基体降到最低公共顶面、分区抬升）、
`features/roundovers.py`（顶边 R3 凸圆角四道门 + 根部 R3 凹圆角 θm 反解）、
`features/side_channels.py`（挂耳月牙缺口/张缝/销孔，`depends_on` 顺序契约）、
`views/correspondence.resolve_frame_mirrors`（帧镜像裁决）——最后一条 `[GAP]`
（bracket 两条）随之消灭，验收表 **9 绿**。
**密集大图视图分离 2026-10-12 落地**（YZYX 齿箱上盖——新框架第一个密集大图：
图幅 1830×1260、5 视图，此前 9 个靶子全是间距宽松的小件）——三堵墙：
①`view_detector._frame_by_long_lines` + `_sheet_frame` 图框/家具识别（剥框后
切分阈值 71.28/50.40 → 47.29/34.86；家具 16 handle 记进 `Drawing.sheet_frame`）；
②两段式聚类（先全局切行、再行内切列）在"同列上下堆叠、邻列视图 y 跨度盖住空隙"
上**结构性失效**（「c 向」与下方大拱之间空着 110.7mm 仍被俯视图盖进同一行，
且两者 x 完全重合 ⇒ 永不切开）⇒ 改递归 `_xy_cut`（每块先问 y 再问 x），
5 视图与打印件逐位对上；③2×N 布局下"恰好一个视图同时有行、列伙伴"的判据失效
⇒ `view_typer._extent_score` **三等定律裁决**（列伙伴同宽=长对正、行伙伴同高=
高平齐；满足 +1/违背 −1，唯一最大且 >0 才裁决，否则照旧报疑）⇒ V1 +2 判 FRONT。
**特征树 0 → 22**；107 项拦路疑问 ⇒ 门控按设计拒绝发射，`--force` 照建
**+394%**（38.4M vs v15a 7.78M，bbox z 375 vs 203）。**§C6 第一刀收口
（v0.6.28）**：拦路 **107 → 10**——90 条"中心线定出 3D 轴但没给半径"实为把
中心线当**无限长直线**全组合的伪轴（V3 306 对 → 真交点 **18** 处），修正 =
线段交叉判真（`EXT_TOL`）+ 重复实体去重 + **交点上的圆补半径**（18/18 有圆；
经 `merge_section_axes` 并进已有特征/分区，一律不新建特征）；特征树逐位不变。
**§C6 第二刀第一段（v0.6.29）**：向视图语义「c 向」+ MTEXT 转义解码，拦路
**10 → 8**。「c 向」此前被整条读成局部剖视图 ⇒ 三条**全伪**的阻塞疑问
（剖切种类读不出/无剖面线/切平面位置未知）；实测该视图零剖面线 + 波浪断裂线
[8A9] + R30 弧 + 40/15/30 三个尺寸 ⇒ 是**向视图**（按箭头投射、位置自由）：
`text_parser` 新增 `TextKind.DIRECTION_VIEW`（「X 向」不再产 CutSpec，
「c 向剖视」仍走剖面路径）、`view_typer` 给向视图专用 UNKNOWN_VIEW 疑问，
且向视图**留在 views 里参与三等定律**（拿掉 V2 会让 V0/V1 得分打平、主视图
裁不出来）；顺带 `strip_mtext_codes` 解 `\U+XXXX` 转义与**大写** `%%C/%%D/%%P`、
认 `∅/Ø` 与 `~` 分隔符——实测 `8~\U+220513`、`%%C215` 整条读不出（Phase D
的前提修复）。余 8 条 = **V3 圆"找不到间距 2r 的轮廓对"**，卡点是 **V0 是
半剖图**（半外形侧按简化画法省隐藏线，全局 `draws_hidden=True` 把"无轮廓对"
误当强负证据）⇒ 下一段 = **Phase D 孔标注绑定**（图上明写的 `n~∅d 深h` 给
直径/数量/深度），立项见 `docs/ASSESSMENT_20261006.md` §C6。
**§C6 第二刀第二段（v0.6.30，Phase D）已收口**：`n~∅d 深h` 读成结构化调用
（`conventions/callout.py` 的 `parse_callout`，认 `2~∅10-7H 深25` / `2~∅6锥销孔` /
`∅16锥孔` / `2~M16-7H (通孔)`；`strip_mtext_codes` 是它读得出的前提——`8~\U+220513`、
`%%C215` 此前整条读不出），`features/callouts.py` 同视图半径匹配
（`BIND_TOL=0.05`、排除细实线轮廓）绑圆 ⇒ **12 条 ANNOTATED 孔**
（`annotation:hole_callout`，绑走 15 个圆 = V3 14 + V0 1）。轴向长度靠组内
传播：任一圆从轮廓对读到的 span 传给同组全部圆（span 源即特征自身 handle ⇒
PROJECTION，否则 CONVENTION「同组同构」）；**有深度没 span ⇒ 按设计拒绝
发射**（`4~∅10-7H 深25` 图上只数到 3 个圆、无 span ⇒ 2 条拦路"孔口位置未知"，
按 0 起会横切零件）；绑定圆经 `decompose(exclude=…)` 退出高度分解的分区依据
（图上明写的孔压过"轮廓内圆"的猜测）。YZYX 拦路 8→8 但**换构成**：HEAD 的
r5/r8/r3 三条"找不到间距"被标注定案消解（已裁决 12 条中 4 条记
`recognize:callout_bind`），换来 1 条同心圆（r6.5/r5）+ 2 条按设计拒绝，余
5 条仍是"找不到间距"（r6.5 / r3.5 / r17.8826 / r8.75364 / r6.56123）——半剖
语义仍是那一刀。特征树 **22 → 21**（base 16→6：−10 条伪分区抬升；hole 5→14，
其中 12 条 ANNOTATED）。HLR 归因（A/B，HEAD 逐位复现基线）：探针 11/27 不变
且 16 个失败点相同；TL 缺205/多32 不变、BL 缺359→451/多44→42、TR 缺179→165/
多270→57，仍 [RED]（缺>0：孔建出来了，特征识别整体离达标还远）。OCC 表 9 绿
逐位不变（9 靶子图纸零标注文字，Phase D 对旧路径是 no-op）、selftest 421 项；
SW 表跳过（emit 未改）。
**§C6 第二刀第三段（v0.6.31）收官：拦路 8 → 0**——两个缺口一并补上。
①**无标题半剖推断**（`conventions/section.py` 的 `_infer_untitled`，`section.scope`
的第二条判据路径：视图中心处贯穿竖直中心线 + 剖面材料只在它一侧留 ≥2mm 间隙
⇒ half；材料横跨全幅 ⇒ full；一律 `usable_as_prism=False`、Tier.GUESS、
不产疑问）——**V0 半剖图第一次被识别**（实测 V0=half/左半@中心线 x=3462.94、
V1=full）；②**孔口由同心材料分区顶面定出**（`features/callouts.py` 的
`infer_callout_mouth_spans`：与孔同轴（轴共垂距 ≤0.1mm）、半径更大的**材料**
分区，其实测顶面即孔口面；组内多数派投票）——`4~∅10-7H 深25` 三个圆 2:1 ⇒
span (1661.25, 1686.25) ≡ v15a 真值 z[120,145] 逐位一致（span_how=
`zone:concentric_mouth` ⇒ CONVENTION；同半径圆（孔自己）与"下钻会钻出分区"
的顶面均不算、打平不推）；③`_resolve_questions` 加第三出口：圆边角色被分区/
特征剪影定死（material/cut）时"不存在轮廓对"不再保留疑问——半剖/简化省笔
不是"非圆柱"证据。**特征树 21 → 24**（+3 条 ∅10 孔，axial 1661.25 图纸系）；
零回归对照（`git stash` A/B，HEAD×同图纸×`--force`）：旧 38,309,638.24 / 新
38,303,747.73，差 **5,890.51 = 3×π×5²×25 逐位吻合**（3 孔切出），YZYX 三件套
逐位持平（探针 11/27、TL 205/32、BL 451/42、TR 165/57）；OCC 表 9 绿逐位不变、
selftest **421 → 431**（G14 夹具 4 + H10 推断 6；破坏性证明两条精确判红）。
余 6 条非拦路疑问不变（投影制×3、视图未定性×3）。**§C6 第三刀"拱与圆分家"
（v0.6.32）已收口**：轮廓弧判据（`views/correspondence._profile_arc`，此前
只有"缺口过半落在视图轮廓盒外"一条）补上"**缺口 > 半圈**"——画到的弧不足
半圆时整圆假设无界（半圆拱长得一模一样，拦），画到 ≥ 半圆则是"圆上少画
一截"（YZYX 轴承半孔 180.5°、20160112 键槽截面圆 328.5°、轴测量 r20 半圆槽
180.5° 不再误伤；缺口 189.5° 的塔拱照拦）。YZYX 模型 **38.3M → 7.25M**
（v15a 7.78M 的 −6.8%）、bbox z **375 → 177.5**（v15a 203）、探针 **11/27 →
16/27**（16 个期望 OUT 点 0/16→15/16，余 1 是旧缺陷"垫心"；11 个 FAIL 里
10 个 = 从未读出的甲板/塔壁/平台，原先被假料盖住）；HLR TL 多32→7、BL
缺451→343/多42→2，TR 缺165→199/多57→116（TR = 从 −X 看的复合投影，缺外壳
⇒ 内部棱线暴露成"多"、壳自身的线成"缺"，读出塔壳后自会回收）；特征树
24→23（−1 = 那根 φ375 假圆柱）、拦路仍 0、9 靶子验收表逐位不变、selftest
**431 → 436**（F5 四边界例）。**v0.6.32 时的下一堵墙**（甲板/塔壁/平台——探针 10 个 FAIL 全落这三处）
由后续三刀依次消化：**§C6 第四刀 侧凹槽族六件套（v0.6.33）**新模块
`features/side_recess.py`（俯视「隐藏壁面线+可见唇线+带内端面线」三联 +
剖面槽底/斜肩/平台/壁根圆角/端块外柱面读数 ⇒ 甲板抬升/深腔/浅腔/唇外盒切/
壁根月牙/端块裙；三处根因：`_crescent` 轮廓错把「槽底边+壁面边」写成一条
斜边围出弦-弧透镜、浅腔未登记进 `cuts[sign]` 致月牙 +OVER 过冲段被削、
端块裙按半径取最大选错——R187.5 顶拱与 R95 裙弧同心且都 visible，补端点
判据；`height_zones.build_band` 信号源改「全部可见轮廓边」逐列包络，环
遍历在 T 型拆分点抄近路曾丢 145 顶线）——**探针 9/27 → 27/27**、HLR TR
多 59→55/缺 199→88。**§C6 第五刀 轴回转族 + 母线真弧（v0.6.34）**新模块
`features/axis_revolve.py`——端视图短弧簇（同圆心 ≥3 条互异半径、画不满
轮廓弧）定回转轴（YZYX 给出 r95 侧裙/r110 止口/r145 盘/r187.5 塔四条母线；
子午视图轴向线跨视图 span 取交得真实跨度，R15 端部圆角弧进母线）；
`detect_revolve` 的圆边入口把短弧当「不是圆」丢掉——这里正是那批弧的出口
（不成立零命中，bracket/PF60K 不变）。发射侧 `emit/occ_builder.py` 共用件：
母线严格共圆段（≥4 连续点、每弦包角 ≤60°、同向推进）改画
`GC_MakeArcOfCircle` 真弧 + MakeWire 手工闭环——折线采样在每段转角留环缝
棱线、投影成图纸没有的横线堆（BL 多 387→104）；矩形四角共圆（Thales）
防误判。YZYX 缺 TL 200→151 / BL 293→278 / TR 88→48。**§C6 第六刀 剖面
边界补扫 + 非剖面支持门 + 塔腔（v0.6.35）**——`axis_revolve.axis_bore_scan`
（第 5 节）：短弧表覆盖不到的半径（Ø160 腔/筒/凹填角只在剖面视图里以
「轴向线 × HATCH 材料边界」存在）由 ±1.5mm 材料双探针读出（内侧材料 ⇒
REVOLVE 母线、外侧材料 ⇒ HOLE），必须最后跑（`used` 排除集要看到全树：
塔腔冠 r177.5 在 POCKET 里）——YZYX 6 特征进树；**非剖面视图支持门**
（`_non_section_support`，`BORE_SUPPORT_FRAC=0.5`）：add 段须被 ≥1 个非剖面
子午帧的 visible span 覆盖 ≥50% 才信「绕轴回转」——剖面里一条水平 HATCH
边界线可以同时是后方可见轮廓/平顶实体顶面轮廓的投影（材料双探针无法
区分）。三条过发实锤拒掉：r100 [2478.3,2484.3]、r145 [2604.3,2624.3]、
r140 [2629.3,2645.3]（v15a 截面网格实锤无实心），r145 盘 [2484.3,2504.3]
（V1+V3 双视图支持）保留——同口径复评多 −115（BL 208→118 / TL 49→36 /
TR 75→63）换缺 +5（TL 54→58）；`features/tower_cavity.py` 塔腔（YZYX 式
「冠—拱壳」POCKET：剖面帧里冠线两端各接同心弧对——小弧冠角/大弧塔端部
圆角、弧顶=塔顶母线，端点种子链式追踪 + HATCH 材料侧仲裁直到结合面，
挤出半宽 W=√(R²−h²) 由冠面与塔柱面相贯线推论）——1 特征进树（半宽 60.42
=√(187.5²−177.5²)）；`features/material.py` = HATCH 材料判据工具箱中立化
（tower_cavity 与 axis_bore_scan 共用）。selftest 436 → 439。
**v0.6.36 发射器 B-rep 卫生：孔口膜清理**（定界：**实体材料不变、只移除
不分隔材料的寄生面/恢复流形**）——8 张 z=12 圆盘膜扣住 8 个螺孔口（膜两侧
皆 OUT，HLR 把孔口圆判成隐藏 ⇒ BL 缺 128 段）。删膜不能单独做：圆棱同时
邻膜与孔壁，删膜后成孤儿 ⇒ 正解是**把圆棱并入孔所在平面宿主面的内环**
（宿主重建 + 原地挪棱到宿主曲面 z）。圆棱与宿主差 **25nm**（图纸原生坐标
1553.248475 vs 4 位量化 1553.248500），超 OCC 容差（1e-7mm=0.1nm）250 倍
会报 BRepCheck UnorientableShape(27) ⇒ `_lift_rim_to` 用 UpdateEdge/
UpdateVertex 原地挪（顶点容差 1e-4mm）。护栏加**体积不变**判据：YZYX 的
3 张 plain 膜删后壳不闭合、体积漂 −61.6 万被否决（那是识别侧假料的真边界，
不该由 B-rep 卫生动），bracket 的 4 张真膜照常删。**BL 缺 278→150**、TL/TR/多
全不变、探针 27/27、9 绿逐位不变。
**v0.6.37 剖面材料反证**（`height_zones._rebut_materials`，decompose 的
③b）：高度分解的角色来自「同轴圆半径序奇偶」——俯视几何的猜测（大圆既可能
是凸台顶面、也可能是盲孔口，俯视同形）。剖面图能说死它：若视图**本身带
HATCH**、分区 u 投影区间内 4 层材料覆盖率 ≤2%、同高度带**别处**覆盖率
≥10%（证明这层确实画了剖面线）、≥2 层同时满足 ⇒ 角色翻 cut。YZYX r50 圆
（Ø100 盲孔口）由此翻 cut，**体积 9,690,883.7 → 8,544,416.1**（−1,146,467
≈ π·50²·145 逐位吻合，vs v15a 从 +24.5% 收窄到 **+9.8%**）、**探针 16/27 →
27/27**、BL 的 r50 圆第一次匹配上。⚠️ 采样必须按 **u 投影区间均匀取**
（32 点）而非几何中心点：环形分区的材料在壁上，中心点采样会把有材料的环
误判成空腔（bracket 塔柱 r25.5/r15.7 实测，selftest 4 项拉红后修正）。
**当前下一堵墙**（按影响排序）：①**东端孔上方假料**——高度分解的剪影只收
`u_axis == b1` 的视图（= V1 剖面，只代表剖切面 y=0 的截面），**V0 主视图
（u=y）剪影未参与** ⇒ base_top=80 把东端 y=±140 的薄板区（真实顶面 12）
填到 80，8 个 Ø13 孔口全被埋（BL 缺 32 段孔圆、(147.5,±140) 在 BL 投影里
0 点）；②**Ø100 圆底**——图纸是 U 形圆弧底（A—A 两段 16 段弧
`(-145.17,44.31)->(-107.04,1.67)`），模型平底，孔壁竖线在 z 0..43 成"多"
（TL 多 36→63 即此，新暴露的真实结构差异，非退步）；③塔顶斜线 29 段缺口
（`(14.5,187.5)->(137.5,122.5)` maxd=15.1）。当前评分：TL 缺 56/多 63、
BL 缺 150/多 116、TR 缺 47/多 64；非拦路疑问（V1 剖切面、塔顶三孔族、
#7 的 depth 48.25 疑误）不变。
✅ 无基准三件套（`yz_accept.py`：27
材料点 + 五视图 HLR 评分）建在 **v15a 零件系**上（探针点、`yz_hlr.SPLIT_X=−96.5`
都是零件系常量），新框架模型在**图纸坐标系**——2026-10-13 **零件系变换已落地**
（`yz_frame.py`：推导为**纯平移**、轴序相同，`part = model − (2650.80, 3462.94,
1541.25)`；三件套 `--frame auto` 按 bbox 自动识别，直接可评新框架模型）。
`--force` 模型首评（§C6 起点基线）：**探针 11/27**（11 个"期望 IN"点全过、
16 个"期望 OUT"点全失败——过实，与 +394% 一致）+ **HLR 缺 TL 205 / BL 359 /
TR 179**；横向 ±172.5/±197.5/顶 187.5 已逐位对，缺的全在特征识别。
顺带修正：YZYX `8A9` 是**画在细实线层的 SPLINE 波浪
断裂线**（bbox 与「c」窗口逐位重合）⇒ ASSESSMENT §C4"真实图纸零命中断裂线"
的按图层/线型名扫描**漏了**这种画法。
`src/rebuild/` 现有：`model/`（Claim/geom/geom2d/ids/feature_tree/questions）、
`evidence/`（dxf_reader/model + text_parser）、
`views/`（view_detector + view_typer + correspondence 跨视图对应〔v0.6.32 起
含**拱弧 vs 圆边**双判据 `_profile_arc`：缺口 > 半圈 且 缺口过半在轮廓盒外〕 +
**ring 轮廓环仪器**）、
`conventions/`（**11 条规则**，2026-10-11 起：centerline 对称/阵列、
linetype 断裂/虚线/**细实线**、section 剖切种类/材料（v0.6.31 起含**无标题
半剖/全剖几何推断** `_infer_untitled`）、simplification 螺纹/圆角、
**dimension 尺寸锚点**、**callout 孔标注**（2026-10-15 Phase D：`n~∅d 深h`
→ 直径/数量/深度）——YZYX 手工读图三约定已前移：局部剖几何推断
（「c 向」标题 + 剖面线覆盖比 <0.9 ⇒ local）、细实线=被盖轮廓（Role.THIN，
环提取只认 VISIBLE 自动排除）、DIMENSION「数值↔几何锚点」配对（tier=ANNOTATED），
实测 YZYX C—C 定性 section/scope=local、52 条尺寸 45 锚上、20/3/120 逐位吻合）、
`features/`（recognizer + solver + library + prior + taper_scale 锥化 + **revolve 回转体（含 _cone_zone 锥区：锥台 REVOLVE + 帽切）** + **height_zones 高度分解 + roundovers 圆角 + side_channels 侧通道 + callouts 孔标注绑定（v0.6.31 起含**孔口推断** `zone:concentric_mouth`）** + **axis_revolve 轴回转族**（v0.6.34；v0.6.35 起含**剖面补扫** `axis_bore_scan` + **非剖面视图支持门**） + **side_recess 侧凹槽族六件套**（v0.6.33） + **tower_cavity 塔腔**（v0.6.35，YZYX 冠—拱壳 POCKET）+ **material** HATCH 材料判据工具箱）、`verify/`（compare/coverage/
gate/step_probe/box_probe）、`emit/`（occ_builder + sw_builder）、`report.py`、`inspect.py`、
`rebuild.py`（端到端 CLI）、**`pipeline.py`（唯一入口：`pipeline.rebuild(dxf,
step=|sldprt=|sw=|force=)`）**、`selftest.py`、`verify_legacy.py`。逐阶段叙事与实测数见 `docs/CHANGELOG.md`
顶部「新框架 src/rebuild/」段；`docs/ARCHITECTURE.md` §8 各阶段带 ✅ 状态行。
```bash
python -m src.rebuild.inspect <dxf> [--json|--texts|--dims|--views|--explain HANDLE]
python -m src.rebuild.rebuild <dxf> [--step PATH] [--sldprt PATH|--sw] [--force] [--json]  # 端到端 CLI
python -m src.rebuild.selftest       # 439 项自检（2026-10-17 剖面补扫/塔腔后实测），退出码 0 = 全过（项目无 pytest）
# 拿图纸判一个 STEP（阶段 0 验收入口，**需 cad-occt**；退出码 0/1/2/3 = ACCEPT/REJECT/需确认/出错）
PY=/c/Users/yaoshuo/miniconda3/envs/cad-occt/python.exe
PYTHONIOENCODING=utf-8 $PY -m src.rebuild.verify_legacy <图纸.dxf> <模型.step> [--json]
```
阶段 4 实测（2026-09-28）→ 阶段 5 表（2026-10-07）→ 阶段 6 表（2026-10-09）→
**当前表（2026-10-12 v0.6.25，9 靶子两表全绿；2026-10-11 验证制度化起 OCC 表加
体积/bbox 阈值判红 0.5%/1mm + bracket 缺陷盒·点断言）**：
6 个简单靶子**全部体积逐位吻合**（block_3view / plate_100x60 / flange_d80 /
法兰练习 4 绿 + **l_bracket 19,800 / 图形练习 72,000** 阶段 5 转绿，bbox 差全
0.00；SW 表另核**特征步数 = 特征模型**）；**PF60K** 由阶段 6 转绿、2026-10-12
**残余追平**——26 特征，OCC 261,943.9 vs 金值 261,935.0 = **+0.0034%**（实体 1；
两处残差归零：r8 沉孔 +1,005.3＝correspondence `DUP_TOL` 收紧、锥区 −852.5＝
锥台 REVOLVE + 4 帽切 + 内腔补偿切；余 +8.9 微项不追；SW 261,776.7（−0.06%）
＝发射器口径差，见下）。
**bracket 两条由阶段 7 转绿**——三视图 **191,970.1（−0.01%）** / 剖面图
**192,196.5（+0.11%）**，bbox 差全 0.00、实体 1、11 特征、`blocking()`=0；
OCC 表与 SW 表逐位/毫厘吻合——两个独立发射器（一 OCC 一 COM，无共享代码）
互为交叉验证。
⚠️ **`[GAP]` 是已知结构缺口、不是回归**——当前**一条不剩**（bracket 高度分解
2026-10-10 已做；历史三条均已消灭："基体轮廓取视图包围盒"→轮廓环（阶段 5，
l_bracket/图形练习 +227%/+200% → 逐位）、"多视图回转体识别未做"→
`features/revolve.py`（阶段 6，PF60K −63.05% → +0.06%）、"高度分解未做"→
`features/height_zones.py`（阶段 7，bracket +48.70%/+84.12% → −0.01%/+0.11%））。
r12 的 GUESS(hole|boss) 的「HLR 重合消影推理」通道 2026-10-10 落地（corr
层 `_band_totals` 分壁并集量尺报疑 → bracket 按分区剪影裁决回 boss
（`recognize:hlr_occlude`，一致只记账、相悖回流改写 type）、PF60K r8.5 按
revolve 证据覆盖裁决；9 绿逐位不变，自检 336 项）。
**别为了让表变绿去调发射器**——那会把"没读到"变成"读错了"（体积对了结构全错，
正是本框架要消灭的病）。表上红的地方就是还没读出来的地方，见
`run_rebuild_acceptance.py` 顶部注释。反向同样成立：阶段 7 把 SW 的 top_round
圆角推迟发射后体积 +0.48%→+0.54%（更远离金值），但圆角面从过延伸 578.59
收敛到 453.14 ≈ OCC 453.10——**为结构忠实宁可数值倒退**。
SW 表（2026-10-12 v0.6.25）：**9 绿**。PF60K 转绿靠发射器三修——
`emit/sw_builder.py` 的「切除类草图一律 `SetAddToDB` 关推理捕捉」（#9 键槽
角点被吸到 r8.5 圆，0.45mm 畸变致切除相切失败；吸附与否随视图缩放变）+
「零宽缝环带剥缝 + 整圆改画原生圆实体」（#16 环带补偿切；自重合轮廓 SW
求解器拒绝）。**连锁改善**：bracket #1 base（8 弧 r25.5 整圆）自 62 段折线
改画原生整圆后，SW 与 OCC 口径差 +1,062 → **−8**——SW 三视图
191,962.3（−0.01%）/ 剖面图 191,958.1（−0.02%），旧值 193,032.3/193,032.8
的「+0.54% 发射器口径差」大半正是折线近似的账；PF60K SW 261,776.7
（−0.06%，口径差 −167.2，方向随本轮新特征翻转）。SW 表不判体积阈值——
口径差天然存在，步数一致 + 发射无 bug 即绿。
`sw_builder._defer_top_round`（**SW 专有**：
原生圆角传播由"建角时的上下文"截断——裸基体上净切 578.59、抬升区之后
453.14；`Options`/`OverflowType` 与传播无关）即为此役所得，OCC 建序与
`library.build_order` 工具刀语义不动。
验收表因此按"框架自己的 gate"判失败性质：`blocking()` 非空 ⇒ `[GAP] 按设计拒绝`
（不计 FAIL、也不洗绿）；**一条阻塞疑问都没有却失败 ⇒ 疑似发射器 bug、计 FAIL**。
另有一条已记账的静默默认：`BOSS/HOLE/POCKET/SLOT` 的 `axial_at` 参数缺省时
两个发射器都按 **0** 起（不是图纸读数），并各打一行 `[emit] 特征 #n（…）没有
axial_at ⇒ 沿轴按 0 起`。历史实测症状：bracket 曾基体自 z=2 起而凸台从 z=0
长出、整车 z 向 bbox 46 而基准 44（`bbox 差 +2.00`）——阶段 7 后不再有此症状
（基体/抬升区/孔腔都带显式 origin，bbox 差 0.00）；此条保留为一般约定，
根因永远在识别侧（轴向位置没读出来），不在发射器。

阶段 0 ~ 3 关键成果各留一条（逐阶段叙事与实测数见 `docs/CHANGELOG.md` 顶部
「新框架 src/rebuild/」段、状态行见 `docs/ARCHITECTURE.md` §8）：带描述的剖面
标题读得出来（`B—B 横剖 x=121.89（穿 r25.5 孔轴）`，旧管线正则 `^([A-Z])[-—–]\1$`
把带描述标题整条丢弃——CLAUDE.md 曾记为"缺"的 B—B 圆心基准一直在文件里）、
验证器判据只用图纸+模型（尺度无关比例；spoon REJECT 一句话点名旧管线的强制
拉伸）、`R8.5` 首次读出（旧管线把 `R8_5` 当 `R8` 读——信息论局限表那条在新
框架有解）。阶段 0 验收③ 修正：6 个回归用例里仅 `block_3view` 具三视图 ⇒
ACCEPT，其余 5 个单视图零标注、第三向尺寸不在图上 ⇒ NEEDS_CONFIRMATION。


### SolidWorks 自动化模块 (`src/core/sw_automation/`)

| 文件 | 行数 | 职责 |
|------|------|------|
| `sw_constants.py` | 55 | SW 2025 API 枚举常量（经验证的晚期绑定值），来源：`CAD/SW2025_API_REFERENCE.md` |
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
  多线环开环导致拉伸失败（八边环实测）。
  2026-10-12（`src/rebuild/emit/sw_builder.py`，`_probe_sw_e30.py`）更新：
  ① 吸附门限远不止 0.04mm——键槽角点距 r8.5 凸台圆 **0.45mm** 照样被吸到圆上
  （切出的角棱线与柱面相切 → 切割返回 None），**且吸附与否随视图缩放变**
  （body bbox 变化 → zoom 变化 → 捕捉公差变化），故切除类草图现在**一律**
  no_snap；② 「多线环开环」只发生在相邻端点坐标有浮点噪声时（如弧端点被 SW
  重算）——**顶点对象在相邻边间复用**（逐位相等）即免疫，boss 也可 no_snap
- **零宽缝自重合轮廓被 SW 求解器拒绝**（`_probe_sw_e32.py` 实测）：环带
  （annulus）在单链表示里靠两条首尾对合、**逐位重合**的径向边串成闭环——OCC
  接受（缝零宽无害），SW 画完 194 段仍拒 `FeatureCut3`（返回 None）。正解 =
  `sw_builder._split_zero_width_slits` 剥缝断成独立闭环 + `_full_circle_of`
  把整圆环画成**原生圆实体**（单实体、无端点、免疫推理捕捉）
- **`CreateArc` 的 direction 语义与文档不符**（2026-10-07 四点实验 + bisect 定死）:
  `True` 实测 = **顺时针**；`False` 实测 = **取劣弧**（不是文档写的"逆时针"——
  CCW 走优弧时它会把劣弧画出来）。顺时针**劣弧**传 True 会**静默拒绝拉伸**
  （bracket r3 弧实测：同轨迹传 False 通过）；优弧必须用"顺时针 + 正确端点序"
  表达（换端点序走顺时针 = 同一条优弧）。`sw_builder._sketch_profile` 已按此重写
- **SW 拒绝 30+ 段首尾相接的碎片微线段链**：122 实体（未合并）连纯折线环都拉不出来；
  同一条微链两排、任一排合并即可通过。修为**精确共线无损合并**（叉积 ≤1e-9·|a||b|，
  bracket 微链垂偏 0.000µm，合并前后解析面积逐位相同），122→62 实体即通过
- **SW 草图弧按（圆心+两端点）三点重拟合**：环端点离理想圆 0.3–4.7µm 时读回半径
  偏移（实测 r20→19.9847、r25.5→25.5927），高密度环的体积对账残留 ±0.1–0.5%
  （基体 −0.4942%、全弦对照 +0.0987%，逐位复现）；简单靶子端点精确、不受影响

### 已移除的功能（v0.3.0 起不再维护）

PDF/图像矢量化整条链：`convert_pdf.py`（Zhang-Suen 骨架化 PDF→DWG）、
`src/core/vectorization/`、`io/pdf_importer.py`、`io/image_importer.py`。

## 路径与平台注意事项

- 项目路径包含中文字符，在终端中操作时注意编码。
- **控制台重定向日志是 GBK 编码**：脚本 `>` 重定向输出的日志为 GBK（Windows 控制台默认代码页）。日志混有非 GBK 字符（如 ✓）时 `iconv -f GBK -t UTF-8` 会中途失败，改用 `grep -a`（文本模式）直接读原始文件。
- Windows 环境下 PythonOCC 的 `pip install` 容易失败，务必使用 conda-forge 安装。
- SolidWorks 自动化功能仅限 Windows，需要安装 SolidWorks 2025 和 `pywin32`。
- **`convert_dwg_to_3d.py` OCC 懒加载**: OCC 导入已改为延迟加载（`_ensure_occ()`），仅需 DXF 解析时（如 `dxf_to_sldprt.py` 引用 `parse_shaft_from_dxf`）不再依赖 PythonOCC。该脚本本身是**完整可用的**——包含 DXF 几何解析、旋转体建模、键槽布尔减运算、STEP 导出。
- **版本号同步**（发版时全部要改，当前均为 `0.6.25`，已核对一致）:
  `src/app.py:15` `APP_VERSION` / `src/gui/main_window.py:28` `setWindowTitle` /
  同文件 `:535` 关于对话框 / `CLAUDE.md` 本节 / `README.md`（"当前版本"行
  + 路线图段）/ git tag，外加两个转换器脚本横幅（`dxf_to_3d_general.py` 与
  `dxf_to_sw_features.py` 的 docstring 与结尾 print）。
  惯例：内容入正文即可按 `v0.6.x:` 前缀提交，tag 簿记待下次发版收口；发版 =
  bump 上述全部字符串 + tag 打在收口提交上（2026-10-02 曾"先提交、后收口"致
  tag 落后 HEAD 16 个提交；v0.6.21/v0.6.22 收口已各清一次账，覆盖范围见
  docs/CHANGELOG.md 顶部三节）。
  （2026-10-11 收口：约定沉淀（局部剖几何推断/细实线/DIMENSION 锚点）入账并
  **发版 v0.6.23**——v0.6.22 tag 之后的 5 个提交（8fa7e8b 消影推理 + 三个
  收口提交 + 255e8e8 约定沉淀）一次落定：bump 上述全部字符串 + tag `v0.6.23`
  打在收口提交上。v0.6.23 覆盖：YZYX 手工读图三约定前移进 conventions/
  （10 条规则）+ MTEXT 字体规格码清洗修复，selftest 367 项、9 绿逐位不变）
  （2026-10-11 收口：验证制度化（ASSESSMENT §D：缺陷盒·点断言 + 阈值判红 +
  YZYX 三件套 yz_accept + 例行检查 SOP）入账并**发版 v0.6.24**——bump 上述
  全部字符串 + tag `v0.6.24` 打在收口提交上。v0.6.24 覆盖：`verify/box_probe.py`
  + 验收表 PROBES/阈值判红、yz_probe_mat/yz_hlr/yz_match/yz_accept 入库、
  CLAUDE.md SOP 节，selftest 367 项、9 绿逐位不变、破坏性证明四条判红路径）
  （2026-10-12 收口：PF60K 残余追平（OCC 侧 DUP_TOL/锥台 REVOLVE）+ SW 发射器
  三修入账并**发版 v0.6.25**——两提交（a99bb5e OCC 侧 + dd32a98 SW 侧/文档）
  一次落定：bump 上述全部字符串 + tag `v0.6.25` 打在收口提交上。v0.6.25 覆盖：
  correspondence `DUP_TOL=0.05`、revolve `_cone_zone`、sw_builder `no_snap`/
  `_split_zero_width_slits`/`_full_circle_of`，OCC 表 9 绿 + SW 表 9 绿
  （PF60K 261,943.9 / 261,776.7 两表转绿）、selftest 367 项）
  （2026-10-12 内容已入正文、**未收口**：v0.6.26 提交（5692df4 密集大图视图分离
  ——递归 XY 切分 + 图框/家具剔除 + 三等定律主视图裁决）按惯例只带 `v0.6.x:`
  前缀——tag 仍 `v0.6.25`、8 处版本字符串仍 0.6.25，待下次发版一并 bump。
  该提交已同步更新本文件：新框架节「密集大图视图分离」段、MKL PATH 环境坑、
  8A9 细实线断裂线修正，selftest 367→373（OCC 验收表 9 绿逐位不变））
  （2026-10-13 续未收口：v0.6.27 提交（3b814ac 零件系变换 `yz_frame.py`——三件套
  `--frame auto` 直接可评新框架模型，`--force` 首评 11/27）+ v0.6.28 提交
  （f3ae0ec 中心线交点判真 + 交点圆补半径——YZYX 拦路 107→10、疑问 113→16、
  缺尺寸标注 98→1，特征树逐位不变）同样按 `v0.6.x:` 前缀提交。至此 tag 落后
  HEAD **4 个提交**（5692df4 / b14124e / 3b814ac / f3ae0ec）、8 处版本字符串仍
  0.6.25。两版正文已入本文件新框架节（含 §C6 第一刀收口段）+ ASSESSMENT §C6、
  CHANGELOG 各一节，selftest 373 项、OCC 验收表 9 绿逐位不变）
  （2026-10-14 续未收口：v0.6.29 提交（7418203 向视图语义「c 向」+ MTEXT 转义
  解码——YZYX 拦路 10→8，selftest 373→390，OCC 验收表 9 绿逐位不变）同样按
  `v0.6.x:` 前缀提交。至此 tag 落后 HEAD **6 个提交**（5692df4 / b14124e /
  3b814ac / f3ae0ec / d34997f / 7418203）、8 处版本字符串仍 0.6.25。本版正文
  已入本文件新框架节（§C6 第二刀第一段）；ASSESSMENT §C6 / CHANGELOG 两处
  尚待补）
  （2026-10-15 续未收口：v0.6.30 提交（Phase D 孔标注绑定——YZYX 拦路 8→8
  换构成、特征树 22→21、selftest 390→421、OCC 验收表 9 绿逐位不变）同样按
  `v0.6.x:` 前缀提交。至此 tag 落后 HEAD **7 个提交**（5692df4 / b14124e /
  3b814ac / f3ae0ec / d34997f / 7418203 + 本次）、8 处版本字符串仍 0.6.25。
  本版正文已入本文件新框架节（§C6 第二刀第二段），v0.6.29 的两处欠账
  （ASSESSMENT §C6 / CHANGELOG）于本次一并补为 v0.6.29 + v0.6.30 各一节）
  （2026-10-15 续未收口：v0.6.31 提交（半剖语义识别 + 孔口由同心材料分区顶面
  定出——YZYX 拦路 8→0、特征树 21→24、selftest 421→431、OCC 验收表 9 绿逐位
  不变）同样按 `v0.6.x:` 前缀提交。至此 tag 落后 HEAD **8 个提交**（5692df4 /
  b14124e / 3b814ac / f3ae0ec / d34997f / 7418203 / 1c06418 + 本次）、8 处版本
  字符串仍 0.6.25。本版正文已入本文件新框架节（§C6 第二刀第三段）+ CHANGELOG
  与 ASSESSMENT §C6 各一节）
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
