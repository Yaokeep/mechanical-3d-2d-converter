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

当前版本 **v0.6.12**（详细进度以 `CLAUDE.md` 和 git log 为准）：

- [x] v0.1.0 — 项目脚手架（目录结构、GUI 骨架）
- [x] v0.2.0~v0.5.9 — SolidWorks COM 自动化、DXF→SW 全流程建模、
      DXF→3D 通用转换器（CSG 体积求交 + P0 内部特征 + P1 投影验证 +
      P2 注解驱动 + 三视图分离）
- [x] v0.6.0~v0.6.5 — P3 复杂图纸健壮性（reducer 263 边靶子）与
      闭环验证链驱动的精度修复（PF60K 法兰盘体积偏差 10,355 → 2,812，
      凸台/键槽/安装孔/锥面过渡逐一还原，回归套件 6/6）
- [x] v0.6.6~v0.6.12 — SW 原生特征模型（`dxf_to_sw_features.py`，18 特征
      全成）与闭环验证链工具修复（`model_to_drawing` 线型 bug、
      `compare_models` 重写），PF60K 体积偏差收敛至 <0.1%；bracket angker
      闭环验证驱动的棱柱居中量可信度门控（v0.6.12）
- [ ] GUI 内 PythonOCC 集成 — `src/gui/view3d`、`projection`、
      `reconstruction` 模块骨架已就绪，待接入（核心算法已在根目录
      独立脚本 `dxf_to_3d_general.py` 等中完整实现）
- [ ] v1.0.0 — 测试、打包与发布

## 许可证

MIT License. OpenCASCADE Technology 版权所有 © Open CASCADE SAS.
