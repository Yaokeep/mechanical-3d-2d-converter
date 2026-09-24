# 机械三维二维图互转

> Mechanical 3D-2D CAD Converter

机械工程 **三维模型 ↔ 二维工程图** 双向互转桌面工具。

## 功能特性

- 🔄 **3D → 2D 投影**：标准三视图（正视图 / 俯视图 / 右侧视图）、等轴测图、剖面图、HLR 消隐
- 🔧 **2D → 3D 重建**：从 DXF 草图拉伸（Extrude）/ 旋转（Revolve）生成 3D 实体
- 👁️ **交互式可视化**：3D 模型旋转/缩放/平移（PythonOCC），2D 工程图多视图布局（QGraphicsView）
- 📐 **自动标注**：线性尺寸、半径、直径自动生成
- 📁 **多格式支持**：STEP (AP203/214)、IGES (5.1/5.3)、STL (ASCII/Binary)、DXF、BREP

## 技术栈

| 组件 | 技术 |
|------|------|
| GUI 框架 | PyQt6 |
| CAD 内核 | OpenCASCADE Technology 7.7 (PythonOCC) |
| DXF 读写 | ezdxf |
| 数值计算 | NumPy |
| 日志 | Loguru |

## 环境要求

- Python 3.10+
- Windows 10+ / Linux (Ubuntu 20.04+) / macOS 12+
- **pythonocc-core** 建议通过 conda-forge 安装

## 快速开始

### 1. 创建虚拟环境

```bash
# 使用 conda（推荐，Windows 下更稳定）
conda create -n cad-converter python=3.11
conda activate cad-converter
conda install -c conda-forge pythonocc-core=7.7.2

# 安装其他依赖
pip install -r requirements.txt
```

### 2. 启动应用

```bash
python main.py
```

### 3. 基本操作

1. **打开 3D 模型**：`文件 → 打开模型` 选择 STEP/IGES/STL 文件
2. **生成工程图**：`3D→2D 投影 → 生成三视图` 自动生成 2D 工程图
3. **2D 转 3D**：`2D→3D 重建 → 拉伸建模` 导入 DXF 草图并拉伸为 3D 实体
4. **导出**：`文件 → 导出` 选择目标格式（STEP/IGES/STL/DXF）

## 项目结构

```
机械三维二维图互转/
├── main.py                     # 应用入口
├── requirements.txt            # Python 依赖
├── README.md
├── src/
│   ├── app.py                  # QApplication 初始化
│   ├── gui/                    # GUI 层
│   │   ├── main_window.py      # 主窗口
│   │   ├── view3d/             # 3D 视图（PythonOCC 渲染）
│   │   ├── view2d/             # 2D 工程图视图（QGraphicsView）
│   │   ├── dock_widgets/       # 可停靠面板（项目树/属性/控制台）
│   │   └── dialogs/            # 对话框（导入/导出/建模）
│   ├── core/                   # 核心逻辑层（与 GUI 解耦）
│   │   ├── model/              # 数据模型（Document / ShapeNode / ProjectionData）
│   │   ├── io/                 # 文件导入/导出（STEP / IGES / STL / DXF）
│   │   ├── projection/         # 3D→2D 投影引擎（HLR / 三视图 / 轴测图 / 剖面图）
│   │   ├── reconstruction/     # 2D→3D 重建引擎（线框 / 面 / 拉伸 / 旋转）
│   │   └── annotation/         # 自动尺寸标注引擎
│   └── utils/                  # 工具模块（配置 / 日志 / 线程 / 单位换算）
├── resources/
│   └── styles/                 # QSS 主题（亮色 / 暗色）
└── tests/                      # 测试
```

## 开发路线图

当前版本 **v0.6.19**（详细进度以 `CLAUDE.md` 和 git log 为准）：

- [x] v0.1.0 — 项目脚手架（目录结构、GUI 骨架）
- [x] v0.2.0~v0.5.9 — SolidWorks COM 自动化、DXF→SW 全流程建模、
      DXF→3D 通用转换器（CSG 体积求交 + P0 内部特征 + P1 投影验证 +
      P2 注解驱动 + 三视图分离）
- [x] v0.6.0~v0.6.5 — P3 复杂图纸健壮性（reducer 263 边靶子）与
      闭环验证链驱动的精度修复（PF60K 法兰盘体积偏差 10,355 → 2,812，
      凸台/键槽/安装孔/锥面过渡逐一还原，回归套件 6/6）
- [x] v0.6.6~v0.6.13 — SW 原生特征模型（`dxf_to_sw_features.py`，18 特征
      全成）与闭环验证链工具修复（`model_to_drawing` 线型 bug、
      `compare_models` 重写），PF60K 体积偏差收敛至 <0.1%；bracket angker
      闭环验证驱动的棱柱居中量可信度门控（v0.6.12）；隐藏整圆解析
      宽容化——旧图纸显式 HIDDEN 线型圆不再被跳（v0.6.13）
- [x] v0.6.14 — bracket 闭环三特征修复（槽端通顶竖槽 + R12/R9 反向刀 +
      Y 孔 R12−R9 信号 + Cut(compound) 静默失败根因）
- [x] v0.6.15 — 多视图 + 剖面图识别重建：剖面视图作为形状约束棱柱与
      标准棱柱求交（`_build_section_prism`），出图侧自动结构分析追加
      剖面图（`section_view.py` + `model_to_drawing.py` 完整图纸）
- [x] v0.6.16 — 剖面图纸重建弧端方形 + Y 孔缺失修复：竖线带二次归带
      （x 聚簇 ±2.5 + y 并集）修复融合投影拆散的竖线段被 0.8×视图高
      过滤 → 深槽刀组（R12/R9 弧端反向刀 + Y 孔 r3）在剖面图纸失配；
      剖面图纸重建 201,112 → 199,267（+4.75% → +3.79%）
- [x] v0.6.17 — 臂端槽端圆形根因修复：`_weld_ring_vertices` 微段链
      端点保护（并查集传递合并曾把 HLR 圆环微折线链焊成一点 → 链边
      零长被跳 → FixConnected 斜线补接，轮廓 Y[−4,7] 不对称收窄）；
      深槽刀组按基准截面实测重构（全高通槽盒去楔形盖、锥台带反刀、
      反刀盒左界对准凸台右缘 83.72、Common 先裁剪防 Cut 卡死、
      深槽激活跳过 UnifySameDomain 防共面卡死）；`compare_models.py`
      加 `--split-axis` 按 x/y 段拆分；剖面图纸净差 +7,105（+3.70%）
      多余 8,836 / 缺失 1,730（臂端 x[165,166]/[167,168] 与基准 0/0
      完全一致）；三视图 −520（−0.27%）多余 1,499 / 缺失 1,989；
      简单回归 6/6
- [x] v0.6.18 — 用户 viewer 标记三缺陷根因修复：跑道槽端头方形
      （矩形腔刀 x 越界切掉 R6 半圆刀外侧弧角，腔盒收窄到两圆心之间
      [−82,−32]，端头弧面由半圆刀接管）；侧边 0.1mm 薄壁未分开
      （深槽刀左界 +0.1 → −0.1）；挂耳处全高怪棱（旧锥台反刀线性
      R12→R9 中段比真弧细 0.83~1.2 + 保护盒左面 83.72 定死大于凸台面 +
      球台整体缺失，重写为臂环盘 revolve+球台+弦棱+腹板五保护体切割链）；
      剖面图纸净差 +7,307.69（+3.81%），修复前旧代码 +7,104.99 与
      v0.6.17 历史基线逐位一致（净 +202.7 = 修复净加材料效应非回归）；
      简单回归 6/6
- [x] v0.6.19 — 两处独立修复：
      ① 删除"坐标归一化"（v0.5.4 起的 `Fix 1`）——该块假设「模型应以
      原点为中心」并把 bbox 中心平移到原点，而本项目模型坐标就是图纸
      坐标系（基准中心不在原点）→ bracket 被强行左移 0.4947mm，凸台被
      推出验证盒（盒内材料 32.9 → 25.0，基准 32.5）即用户 viewer 标记的
      "凸台右弧空缺"（#1 间隙 1.59mm / #2 间隙 2.59mm）；删除后标记盒
      恢复（#1 31.4 / #2 31.3 vs 基准 32.5 / 31.5），dx 口径 63.65 → 63.56；
      ② 新增"整圆附加环"——俯视图凸台整圆与叉臂轮廓相切时，外环遍历把
      凸台右弧当"圆 ∪ 叉臂"并集的内边界淘汰，按"挂线另一端距圆心 > r+0.3"
      判据合成 36 段弧环 Union 回棱柱（`NO_EXTRAS=1` 可关）。
      受控实验分离度量（v4 三视图）：多余 2,898.96 →（归一化）1,472.04 →
      （+extras）903.16，缺失 2,356.21 → 936.68 → 935.28，重合 98.8%→99.5%；
      剖面图纸 多余 8,946.99→8,183.39 / 缺失 1,638.74→698.10 / 99.1%→99.6%；
      PF60K `CSG_WELD=1` 263,119.41 逐位一致；简单回归 6/6
- [ ] GUI 内 PythonOCC 集成 — `src/gui/view3d`、`projection`、
      `reconstruction` 模块骨架已就绪，待接入（核心算法已在根目录
      独立脚本 `dxf_to_3d_general.py` 等中完整实现）
- [ ] v1.0.0 — 测试、打包与发布

## 许可证

MIT License. OpenCASCADE Technology 版权所有 © Open CASCADE SAS.
