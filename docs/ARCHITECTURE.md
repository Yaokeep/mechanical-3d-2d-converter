# 架构设计：图纸理解与三维重建

> 本文档是 `src/rebuild/` 的设计基线。与 `CHANGELOG.md`（逐版本根因叙事）分工：
> 本文讲**应该是什么样**，CHANGELOG 讲**曾经发生过什么**。

---

## 0. 本文档的地位

本文是**重写**的设计基线，不是对现有 `dxf_to_3d_general.py` 的增量说明。

- 代码落在新包 `src/rebuild/`，根目录提供薄 CLI 入口（沿用本项目"根目录脚本 = 可用实现"的惯例）
- `dxf_to_3d_general.py`（8957 行）降级为**兜底几何重建器**，见 §9
- `src/core/reconstruction/` 等骨架**不再续写**，见 §11

---

## 1. 为什么重写

### 1.1 现状的病根：没有中间表示

当前管线是**几何进、几何出**：

```
三个视图轮廓 → 各自拉伸成棱柱 → 布尔求交 → 一个 CSG 疙瘩
```

中间没有任何"零件是什么"的模型。全部信息以裸 float 存活。由此推出三个无法靠打补丁解决的后果：

| 后果 | 具体表现 |
|---|---|
| **无法追溯** | 调试只能靠写探针脚本。现存 **67 个 `_*.py`**——这个数量本身就是症状 |
| **无法验证** | 没有基准模型就不知道对错。spoon 被重建成 Y=2mm 薄片（期望 25）仍打印"3D 转换成功" |
| **无法局部化** | 误差只能整体看体积差，不知道是哪个特征错了。bracket 的剩余误差靠 `_probe_boxes.py` 人工定位到"臂区方块" |

### 1.2 真正的能力缺口：只读了一个通道

工程图的信息装在**两个通道**里：

| 通道 | 内容 | 现管线 |
|---|---|---|
| 几何 | 轮廓走向、圆、弧 | ✅ 读 |
| **符号** | 尺寸值、公差、代号、约定、剖切位置 | ❌ **基本没读** |

证据（2026-09-28 实测）：

- `bracket_angker_三视图_v4.dxf`：`TEXT=0, DIMENSION=0` —— 纯 HLR 线框
- `bracket_angker_图纸_20260922_剖面图.dxf`：`TEXT=12`（全是视图标签/剖面标记）、`DIMENSION=0`
- 那张图纸的 TEXT 里明写着 `B—B  剖视 x=121.89（切 r25.5 轴）`，而 CLAUDE.md 记着剩余误差的抓手是"**缺的是 B—B 圆心对齐的可靠基准（俯视图圆组）**"——**要找的信息一直在文件里**
- 代码 `dxf_to_3d_general.py:618` 的正则 `^([A-Z])[-—–]\1$` 要求整串**恰好**是标签，带描述的标题落进 `else` 被整条丢弃（连 `x=121.89` 和 `r25.5` 一起）

**结论**：CLAUDE.md 的"信息论局限"表里，有相当一部分不是图纸这个媒介的局限，而是**测试图纸不带标注 + 代码不读符号通道**共同造成的。这个区分决定通用性能走多远。

### 1.3 为什么"更聪明的几何"救不了

现管线在解一个**符号问题**，却只有**几何工具**：

- 所以必须逐件手调刀组（bracket 的 `_bx1=83.72`、`r25.5@(58.22,0)`、五保护体）——**那是在反推本来明写的尺寸**
- 所以 `NO_EXTRAS` / `CSG_WELD` 这类开关会改变结果——同一个零件两套答案，因为判据不唯一

补丁能修精度，改不了**范式**。

---

## 2. 目标与非目标

### 目标

1. **通用性**：覆盖任意有正规标注的棱柱类 / 回转类零件，靠通用算法而非逐件调参
2. **可知**：任何数值都能追到图纸依据（`explain` 查询取代探针脚本）
3. **可验**：无基准模型也能判断重建对错（重投影 + 覆盖率）
4. **可拒绝**：信息不足时明确报错并列出缺什么，**绝不静默产出坏模型**

### 非目标（明确不做）

| 非目标 | 理由 |
|---|---|
| 自由曲面重建（勺/叶片/叶轮） | **定义域外**。制图标准没有表达自由曲面的语法，人类工人同样做不到。正解 = 识别并拒绝 |
| 形位公差（位置度/基准体系）语义 | 约束的是**公差**不是**名义形状**。重建名义几何可整体忽略 |
| 装配图 → 装配体 | 单件重建的延伸问题，本期不做 |
| 扫描件/手绘/非标准图纸 | 长尾，见 §12 |

---

## 3. 三条核心原则

### 原则一：系统里不存在裸数值

每个数字都是一个 `Claim`——带依据、带方法、带置信度、带备选。

这一个决定把"第 1~4 层"从四个功能变成**一个结构上的必然结果**：

| 层 | 在框架里是什么 |
|---|---|
| 1 读符号 | Evidence 构建，产出 `method="dimension"` 的 Claim |
| 2 约定语法 | 从 Evidence 推 Claim，`method="convention:*"` |
| 3 零件先验 | `method="standard_series"` / `"constraint_solve"` + 备选剪枝 |
| 4 知道拒绝 | **查 Claim 的置信度与剩余备选**——是查询，不是模块 |

### 原则二：歧义不提前消解

"这个圆是孔还是凸台"在俯视图里**完全同形**，要看主视图的虚实线才能定。

- 现管线：一上来选一个环去拉伸，选错就永远回不来
- 新框架：**同时保留两个假设**，让约束和验证去剪枝；剪不完的进"待确认"

### 原则三：仪器先于引擎

验证器先于重建器。没有验证器时，每一次改动都无法区分"变好了"与"换了个地方错"。

阶段 0 刻意把验证器**指向旧管线**——见 §8。

---

## 4. 中间表示（IR）

### 4.1 Claim

```python
# src/rebuild/model/claim.py

class Tier(IntEnum):
    """置信度分级。顺序即优先级，gate 按此判定。"""
    ANNOTATED = 5   # 图上明标（尺寸文字 / DIMENSION 实体）——最可信
    CONVENTION = 4  # 按制图约定推出（中心线⇒轴线、HATCH⇒被剖到）
    DERIVED   = 3   # 由约束求解得出（尺寸链闭合推出未标尺寸）
    PROJECTION= 2   # 由跨视图对应 + 投影射线得出
    PRIOR     = 1   # 按标准/先验推测（标准值吸附：实测 7.94 → R8）
    GUESS     = 0   # 兜底启发式——一律进"待确认"

@dataclass(frozen=True)
class Claim(Generic[T]):
    value: T
    method: str                      # "dimension" | "convention:centerline" | "constraint" | ...
    tier: Tier
    evidence: tuple[EvidenceRef, ...] = ()
    alternatives: tuple[T, ...] = ()  # 未消解的分支；非空即"待确认"
```

**约定**

- `alternatives` 非空 ⇒ 该 Claim 未定，gate 必须降级处理
- `evidence` 为空 ⇒ 只允许 `tier ∈ {PRIOR, GUESS}`
- 不提供 `__float__` 等隐式转换——**强制显式 `.value`**，让"这里用了个裸值"在代码审查时可见

### 4.2 证据模型

```python
# src/rebuild/evidence/model.py

class Kind(StrEnum):
    EDGE = "edge"; HATCH = "hatch"; AXIS = "axis"
    DIMENSION = "dimension"; NOTE = "note"; BREAK = "break"

class Role(StrEnum):
    VISIBLE = "visible"   # 粗实线
    HIDDEN  = "hidden"    # 虚线
    AXIS    = "axis"      # 点划线：轴线 / 对称面
    HATCH_BOUNDARY = "hatch_boundary"
    BREAK_LINE = "break_line"   # 波浪线：视图断裂

@dataclass(frozen=True)
class Evidence:
    handle: str            # DXF 图元 handle —— provenance 的锚点
    kind: Kind
    geom: Line | Arc | Circle
    view: ViewId
    role: Claim[Role]      # 角色本身也可能是推出来的
    layer: str

@dataclass
class View:
    id: ViewId
    type: Claim[ViewType]          # front|top|side|auxiliary|section|detail
    method: Claim[ProjectionMethod] # first_angle|third_angle —— 全局约定，判错则整体镜像
    frame: Frame                    # 视图局部系 → 图纸系
    evidence: list[str]             # handles
```

`ProjectionMethod` 必须从**标题栏符号**读，不能靠 "Y 最高→top" 的启发式——第一角/第三角判错会让整个零件镜像。

### 4.3 对应关系（承重点）

```python
# src/rebuild/views/correspondence.py

class CorrKind(StrEnum):
    AXIS    = "axis"     # 视图A中心线 ↔ 视图B中心线 ⇒ 同一条 3D 轴
    POINT   = "point"    # 顶点对 ⇒ 3D 点（投影射线求交）
    FEATURE = "feature"  # 圆(视图A) ↔ 轮廓对(视图B) ⇒ 圆柱

@dataclass(frozen=True)
class Correspondence:
    kind: CorrKind
    refs: tuple[tuple[ViewId, str], ...]   # (视图, handle) 对
    mapping: Claim[Any]                    # 产出的 3D 解释：Axis3 | Point3 | FeatureHint
```

**这是"三维思维"的技术核心。**

- 现管线：三个视图各自拉伸再碰运气求交——代码不知道"top 里的圆"和"front 里那两条竖线"是同一个孔
- 有了对应关系：3D 定位退化成**投影射线求交**，是平凡算术

来源（按可信度）：

1. **中心线共线**：视图 A 里过圆的中心线 + 视图 B 里共线的中心线 ⇒ 同一 3D 轴
2. **尺寸锚点**：DIMENSION 的 `defpoint2/defpoint3` 直接指向被量的两个点；跨视图共享锚点即同一特征
3. **投影方向**：front 给 (x,z)，top 给 (x,y)，配对得 3D 点
4. **几何一致**：等半径圆、共线边（弱，仅作候选生成）

### 4.4 假设模型

```python
# src/rebuild/model/feature_tree.py

class FeatureType(StrEnum):
    BASE = "base"        # 基体（拉伸/回转）
    BOSS = "boss"; POCKET = "pocket"; HOLE = "hole"
    SLOT = "slot"; REVOLVE = "revolve"
    FILLET = "fillet"; CHAMFER = "chamfer"
    PATTERN = "pattern"  # 阵列（含螺栓分布圆）

@dataclass
class Feature:
    id: FeatureId
    type: Claim[FeatureType]              # 类型本身也可能是假设（孔 vs 凸台）
    params: dict[str, Claim[Any]]         # 尺寸参数：半径/深度/位置/方向
    placement: Claim[Transform]
    depends_on: list[FeatureId]           # 布尔序——SW SetAddToDB 那课的教训
    evidence: list[str]                   # handles：这个特征的图纸依据
    source_view: ViewId | None

@dataclass
class Part:
    features: list[Feature]
    symmetry: list[Claim[SymmetryOp]]
    constraints: list[Constraint]
    open_questions: list[OpenQuestion]    # 欠定项：缺什么信息
```

### 4.5 约束

```python
# src/rebuild/features/constraints.py

class ConstraintType(StrEnum):
    # 尺寸
    DIM_VALUE = "dim_value"        # 某参数 = 某值
    CHAIN     = "chain"            # 尺寸链闭合：Σ链 = 总长
    # 几何关系（图纸"示意精确"——关系可信、距离不可信）
    COINCIDENT = "coincident"; TANGENT = "tangent"
    PARALLEL = "parallel"; PERPENDICULAR = "perpendicular"
    CONCENTRIC = "concentric"; COLLINEAR = "collinear"
    SYMMETRIC = "symmetric"; EQUAL_RADIUS = "equal_radius"
    # 投影
    PROJECTS_TO = "projects_to"    # 3D 点 → 视图中的 2D 点
```

**关键判据**：图纸是**示意精确**的——两条线是否相切/平行/同心**可信**，距离**不可信**。所以先抽关系再用尺寸定距离，能大幅减少反推。

---

## 5. 模块结构与依赖规则

```
src/rebuild/
  model/                            中间表示（纯数据）
    claim.py                        Claim[T] / Tier / 备选剪枝
    feature_tree.py                 Part / Feature / Constraint
    ids.py                          ViewId / FeatureId / EvidenceRef
  evidence/                         【第1层】读符号通道
    dxf_reader.py                   原始图元 → 带 handle 的 Evidence
    dimension_parser.py             DIMENSION → (类型, 值, 锚点)；炸开的 TEXT 走兜底
    text_parser.py                  φ/R/±/°/×/均布/剖视标题 → Claim
    role_classifier.py              线型/图层/几何 → Role（含 BREAK_LINE）
  views/
    view_detector.py                证据聚类成视图
    view_typer.py                   标题栏 → 第一角/第三角 + 视图类型
    correspondence.py               ★ 跨视图对应关系
  conventions/                      【第2层】标准知识库（规则一条一模块，增量长）
    centerline.py                   轴线 / 对称面 / 螺栓分布圆
    linetype.py                     虚线 / 点划线 / 波浪线（断裂视图）
    section.py                      全剖 / 半剖 / 局部 / 旋转 / 阶梯剖
    simplification.py               螺纹 / 标准件 / 均布孔 / 圆角不画
    registry.py                     规则注册与调度
  features/                         【第3层】假设空间
    library.py                      特征类型定义与"该长什么样"的预测
    recognizer.py                   证据 + 对应 → 候选特征（可多个，带备选）
    prior.py                        优先数系 / 标准孔径 / 标准圆角 / 可加工性
    solver.py                       约束传播 + 欠定/过定报告
  verify/                           【第4层】
    predict.py                      ★ 特征级预测（解析，无需 OCC）
    reproject.py                    B-rep → 视图，对齐输入视图（需 OCC）
    compare.py                      逐边比对（容差内）
    coverage.py                     双向覆盖率
    gate.py                         接受 / 拒绝 / 待确认
  emit/
    occ_builder.py                  特征树 → OCC B-rep（精确）
    sw_builder.py                   特征树 → SW 原生特征树
  report.py                         人读报告（含 explain 查询）
  pipeline.py                       编排
```

### 依赖规则（架构约束，违反即设计错误）

```
model/       ← 不依赖任何东西（纯数据）
evidence/    → model
views/       → model, evidence
conventions/ → model, evidence, views
features/    → model, evidence, views, conventions
verify/      → model, features        ← 注意：不依赖 emit/
emit/        → model                  （+ OCC / SW COM）
pipeline     → 全部
```

两条硬规则：

1. **`model/` 零依赖**——保证 IR 可独立测试、可序列化、可 diff
2. **`features/` 不得依赖 `emit/`**——验证必须能只看特征树就预测形状，不能靠"造出来再量"。这条保证了验证便宜且能定位到特征

### 解释器依赖分层（工程约束）

本项目三个解释器能力不同（见 CLAUDE.md）。新框架**刻意按解释器能力切分**：

| 层 | 依赖 | 可用环境 |
|---|---|---|
| `model/` `evidence/` `views/` `conventions/` `features/` `verify/predict` `verify/coverage` `report` | ezdxf + numpy | **默认 python 即可**（快） |
| `verify/reproject` `emit/occ_builder` | OCC | `cad-occt` |
| `emit/sw_builder` | pywin32 | `cad-occt` |

即：**符号推理层不碰 OCC**，可以快速迭代。只有几何构造和几何验证需要重环境。

---

## 6. 三个关键机制

### 6.1 跨视图对应（§4.3）

**为什么它是承重点**：把"三维思维"从搜索问题变成算术问题。

一对中心线 Correspondence 的产出：

```
视图 top: 中心线过圆 c=(45.3, 151.1)          （图纸系）
视图 front: 中心线 x=45.3                      （图纸系）
⇒ Axis3(origin=(45.3, 151.1, z_lo), dir=(0,0,1), r=Claim(25.5, ANNOTATED, ...))
```

**这正好是 bracket B—B 缺的那个"可靠基准"**——而图纸标题里就写着 `x=121.89（切 r25.5 轴）`。

### 6.2 约束求解（§4.5）

不是数值优化，是**约束传播 + 一致性检查**：

- **可解** ⇒ 顺序传播（大多数尺寸链非迭代可解）
- **过定 + 冲突** ⇒ **图纸自相矛盾，报警**。这是个特性不是错误——线框与标注不一致，用户必须知道
- **欠定** ⇒ 产出 `OpenQuestion`，gate 据此降级

求解器输出的是**被精化的 Claim**，`tier` 依依据更新（`PROJECTION` → `DERIVED` → 最终可能撞上 `ANNOTATED` 并被其覆盖）。

### 6.3 特征级验证（不是几何级）

特征树知道每个特征**是什么**，所以能**预测**它该在各视图里长什么样：

| 特征 | 俯视（沿轴） | 主视（垂直轴） |
|---|---|---|
| 圆柱孔 | 圆（实线/虚线看朝向） | 两条平行线 |
| 盲孔 | 圆 | 两条线 + 底部 | 
| 凸台 | 圆 | 两条线（实线） |
| 通槽 | 两条平行线 | 矩形 |
| 回转体 | 中心线 + 同心圆组 | 轮廓 |

于是验证变成：**预测 → 在该视图的 Evidence 里找匹配 → 报告 unmatched**。

优势（对比整体重投影逐边比）：
- **误差可局部化到特征**（"特征 #7 预测的圆在俯视图找不到"）
- 便宜（解析，无需 HLR）
- 能区分"漏了一个特征"和"某个特征尺寸错"

`verify/reproject.py`（真 HLR）作为 `predict.py` 的**自校验**：解析预测必须与真实投影一致，不一致说明 `predict.py` 有 bug。

---

## 7. 数据流

```
DXF ──evidence──→ Evidence[] + View[]                        【第1层】
                      │
                      ├──views──→ Correspondence[]            【第1层+对应】
                      │
                      ├──conventions──→ 约定 Claim[]           【第2层】
                      │
                      └──features──→ Part（特征树，含备选）      【第3层】
                                       │
                                       ├──verify/predict──→ 预测 vs Evidence  【第4层】
                                       │      ↑ 不收口就回退剪枝/报 OpenQuestion
                                       │
                                       └──emit──→ OCC B-rep / SW 特征树
                                                      │
                                                      └──verify/reproject──→ 与原图比对
                                                                              【第4层】

每阶段都写 report：读到了什么 / 推了什么（tier）/ 缺什么（OpenQuestion）
```

**收敛条件**：`verify/gate` 判定通过才输出。判不过时，不是"照常输出 + 警告"，而是**拒绝并列出 OpenQuestion**。

---

## 8. 阶段计划

每阶段都必须产出**可运行、可对比**的东西，不允许"全写完再测"。

### 阶段 0：IR + 证据层 + 验证器（指向旧管线）

| | |
|---|---|
| **交付物** | `model/claim.py`、`model/feature_tree.py`（最小）、`evidence/*`、`views/view_detector.py`、`verify/{compare,coverage,gate}.py`、`report.py`、CLI `python -m src.rebuild.inspect <dxf>`、CLI `python -m src.rebuild.verify_legacy <dxf> <step>` |
| **关键** | 验证器先**指向现有 `dxf_to_3d_general.py` 的输出**，不写新重建器 |
| **验收** | ① `verify_legacy` 在 **spoon 上必须 REJECT**（现在静默成功——这是验证器是否真的在工作的判据）<br>② 在 bracket 三视图 + 剖面图纸上 ACCEPT，报告的覆盖率与 CLAUDE.md 基线自洽<br>③ 6/6 回归用例 ACCEPT<br>④ `inspect` 在剖面图纸上**读出 `B—B x=121.89 r25.5`**（现管线正则丢弃的那条） |
| **为什么先做** | 拿到：验证器被证可用 + 免基准回归线架 + 当前管线失败模式的量化地图。然后才在新验证器盯着的情况下重写重建器 |

### 阶段 1：视图 + 对应关系

| | |
|---|---|
| **交付物** | `views/view_typer.py`（第一角/第三角）、`views/correspondence.py` |
| **验收** | bracket 上自动产出 B—B / C—C 的 3D 轴线（与图纸标题所写 `x=121.89 r25.5` 一致）；中心线共线匹配在 6 个回归用例上无误配 |
| **依赖** | 阶段 0 |

### 阶段 2：Conventions 知识库

| | |
|---|---|
| **交付物** | `conventions/{centerline,linetype,section,simplification}.py` + registry |
| **验收** | 每条规则带独立测试；进入"断裂视图"识别（现管线完全没处理——断裂视图会被当完整视图，直接搞错尺寸） |
| **依赖** | 阶段 1 |
| **性质** | **长尾，永远长不完**。但每条规则独立可加、可测、不影响已有 |

### 阶段 3：特征识别 + 求解器

| | |
|---|---|
| **交付物** | `features/{library,recognizer,prior,solver}.py` |
| **验收** | 特征树可解释 bracket 全部已标注特征；尺寸与标注一致；`prior` 的标准值吸附解决 CLAUDE.md 信息论局限表中"R8 vs R8.5"一条 |
| **依赖** | 阶段 2 |

### 阶段 4：Emitters + 汇流

| | |
|---|---|
| **交付物** | `emit/{occ_builder,sw_builder}.py`；`dxf_to_sw_features.py` 改为**消费**特征模型 |
| **验收** | 与 6/6 + bracket + PF60K 基线可比；SW 特征树可编辑、特征数与特征模型一致 |
| **依赖** | 阶段 3 |

---

## 9. 现有资产处置

| 资产 | 处置 |
|---|---|
| `dxf_to_3d_general.py`（8957 行） | **保留为兜底几何重建器**——用于无符号信息的图纸。有价值部分（环提取、视图分离、CSG）拆成模块供复用；其余由 `evidence/` `views/` 重写取代。**不再此文件上做功能增强** |
| `dxf_to_sw_features.py` | 它的**输出形态就是终点**（SW 原生特征树）。但现在是从 CSG 结果切片**反推**特征——等于把烧掉的信息再猜一遍。阶段 4 改造为**直接消费**特征模型 |
| `model_to_drawing.py` / `section_view.py` | 出图侧**必须开始产标注**，否则第 1 层没东西可读。这是阶段 0 的并行前置项 |
| `compare_models.py` | 有基准时继续用；无基准时由 `verify/` 接管 |
| **67 个 `_*.py` 探针** | 大部分由 `report.py` + `verify/coverage` 取代。**探针数量是"系统无法自我解释"的症状**——有了 provenance 与覆盖率，它们变成一次 `explain` 查询 |
| 6 个回归用例 / bracket / PF60K 基线 | 全部保留为验收靶子，逐阶段必须保持可比 |
| `CSG_WELD` / `NO_EXTRAS` 开关 | 属旧管线；新框架下**判据应唯一**，不保留此类环境开关 |

---

## 10. 测试策略

### 10.1 读图器与重建器解耦测试

出图侧**已知真值**（它自己知道每个尺寸和特征），于是可以分层验证：

```
真值模型 ──出图(带标注)──→ DXF
                              │
                              ├──读图器──→ Claim 集合 ──比对真值──→ 【读图器正确性】
                              │
                              └──重建──→ 特征模型 ──→ 造几何 ──→ 重投影 ──→ 与原图比对
                                                                    【重建正确性，免基准】
```

现在这两个正确性混在一起，出错时分不清是**没读懂**还是**没造对**。

### 10.2 三层验收

| 层 | 判据 | 需要基准模型？ |
|---|---|---|
| 读图 | 读到的 Claim 值/层级 vs 出图侧真值 | 否 |
| 重建（内） | `verify/predict` 的预测 vs 图内 Evidence | 否 |
| 重建（外） | 重投影逐边比对 | 否 |
| 重建（绝对） | `compare_models.py` vs 基准 STEP | 是（仅 bracket/PF60K） |

### 10.3 回归纪律

- 沿用本项目既有铁律：**验收以实际生成的模型为准**，不以代码或日志数值吻合为准
- 每阶段结束必须重跑 6/6 + bracket 双基线 + PF60K，报**净差/重合**并标注口径（见 CLAUDE.md 口径注：旧值配 dx=63.65、新值配 dx=63.56）
- Claim 集合的 diff 是新的回归信号——比体积差有信息量

---

## 11. 与现有代码的迁移

### 骨架不再续写

CLAUDE.md 记 `src/core/projection/`、`src/core/reconstruction/`、`src/core/annotation/` 为"骨架待集成"。**本设计明确放弃这条路**：

- `core/reconstruction/`（`WireMaker`/`FaceBuilder`/`ExtrudeBuilder`/`RevolveBuilder`）的分解方式正是**几何优先**思维——它假定"先有线和面，再有零件"。新框架的入口是 `evidence/`（先有依据和 Claim）
- 因此**不要**去填这些 `# TODO`。它们应由 `src/rebuild/` 取代，最终删除

### 与 GUI 的关系

`src/rebuild/` 是纯库，无 GUI 依赖。GUI（`main.py`）当前起不来（无 PyQt6），且其核心算法是骨架——**新框架不为其做适配**。接 GUI 是独立课题。

---

## 12. 边界与非目标（诚实清单）

### 域外——做不到，且不该试

| 项 | 理由 |
|---|---|
| 自由曲面（勺/叶片/叶轮） | 制图标准无表达语法。**人类工人同样做不到**——工业上这类零件走 3D 模型或型值表，不走三视图 |

**正确行为**：在视图理解阶段就识别出来，**明确拒绝**并建议改走 3D 输入。而不是像现在硬造一个 2mm 薄片报成功。

### 真难——长尾，不承诺

| 项 | 性质 |
|---|---|
| 第 2 层标准枚举 | 累但不难，但**永远长不完** |
| 第 1 层渣图（扫描件/手绘/非标准） | 真正困难，需 OCR + 容错解析 |
| 第 3 层特征分类 | 规则可覆盖大部分（机加工件高度模式化）；ML 是兜底不是起点 |

### 需要重判的历史结论

CLAUDE.md"信息论局限"表中，以下条目**在读出符号通道后可能不再成立**，须逐条回图纸复核是否真有标注：

- `R8 vs R8.5 凹槽半径差`（图纸若标 R 值则不是局限）
- `φ3.3 沉头锥`（若标"沉头 φ5.5×90°"则可解）
- `F 段顶 3mm 环`（若有尺寸标注则可解）

真·不可修的只剩"画图精度级"一类（如 `φ3.3/φ5.5 孔位 0.1mm 差`——低于图纸绘制精度）。

---

## 13. 术语表

| 术语 | 含义 |
|---|---|
| **Claim** | 带依据/方法/置信度/备选的数值容器。系统内唯一的数值载体 |
| **Tier** | 置信度分级：`ANNOTATED` > `CONVENTION` > `DERIVED` > `PROJECTION` > `PRIOR` > `GUESS` |
| **Evidence** | 图纸里的一个图元（带 handle），未做解释 |
| **Correspondence** | 跨视图的对应关系，是 3D 定位的依据 |
| **Feature** | 3D 假设空间里的一个特征（孔/凸台/腔/…） |
| **解释域** | 制图标准覆盖的零件品类。域内信息充分；自由曲面在域外 |
| **OpenQuestion** | 欠定项——缺什么信息才敢下结论 |
| **gate** | 验收门：接受 / 拒绝 / 待确认 |
