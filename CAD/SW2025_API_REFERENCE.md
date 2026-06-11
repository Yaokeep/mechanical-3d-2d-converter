# SolidWorks 2025 (33.0.0) VBA API — 经验证参考

> 通过 45 轮递进验证宏确认的 SW 2025 API 正确调用方式。
> 验证日期: 2026-06-09 ~ 2026-06-11

---

## 1. 核心编码规则

### 1.1 COM 晚期绑定 — 禁用括号语法

```vba
' ✅ 正确: 不用括号, 无返回值
swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0

' ❌ 错误: 用括号捕获返回值 — 可能返回 False (即使成功)
boolstatus = swModel.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
```

### 1.2 防假阳性 Bug

**SW 2025 关键 Bug**: `On Error Resume Next` 下 `Set swFeat = SomeMethod(...)` 失败时，`swFeat` **保留上次成功调用的旧值**！

```vba
' ✅ 正确: 每次调用前清空
Set swFeat = Nothing
Err.Clear
Set swFeat = swFeatMgr.SomeMethod(...)
Debug.Print IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number

' ❌ 错误: 不清空 — 失败时 swFeat 仍是上一步的成功值 → 假 PASS
Set swFeat = swFeatMgr.SomeMethod(...)
```

### 1.3 单位系统

**所有 API 参数使用米 (meters)**: `mm / 1000 = meters`

| mm | meters |
|----|--------|
| 1mm | 0.001 |
| 10mm | 0.01 |
| 50mm | 0.05 |

### 1.4 VBA `_` 续行符不能跟注释

```vba
' ❌ 致命语法错误: 续行符后不能有任何字符 (包括注释)
Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, _  ' 23: xxx
    False, False, False, False, 0#, 0#, ...)

' ✅ 正确: 单行所有参数, 注释单独一行
' 第1-12参数: ...
Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
```

### 1.5 前视基准面草图必须全部 Z=0

```vba
' ✅ 正确: Front Plane 草图所有 CreateLine 的 Z 坐标全部为 0
swSketchMgr.CreateLine 0.05, 0.008, 0, 0.07, 0.008, 0

' ❌ 失败: Z≠0 导致草图几何退化, 特征方法静默失败 (Err=0 但返回 Nothing)
swSketchMgr.CreateLine 0.05, 0.008, 0.003, 0.07, 0.008, 0.003
```

### 1.6 草图必须在打开状态下调用特征方法

```vba
' ✅ 正确: 只调用一次 InsertSketch2 True 开始画图, 不调用第二次关闭
swModel.InsertSketch2 True   ' 打开草图
' ... 画线 ...
Set swFeat = swFeatMgr.FeatureExtrusion2(...)   ' 草图打开时调用特征

' ❌ 错误: 画完后再调用 InsertSketch2 True 会关闭草图, 特征方法失败!
swModel.InsertSketch2 True   ' 打开
' ... 画线 ...
swModel.InsertSketch2 True   ' 关闭! 草图不再激活
Set swFeat = swFeatMgr.FeatureExtrusion2(...)   ' 失败 → Nothing
```

### 1.7 草图矩形必须跨现有实体表面 (Y 坐标跨表面)

```vba
' 现有轴体表面 Y=0.015 (R=15mm), 矩形 Y 必须部分在体内、部分在体外
' ✅ 正确: Y=0.008~0.018 → 0.008~0.015 在体内, 0.015~0.018 在体外
swSketchMgr.CreateLine 0.05, 0.008, 0, 0.07, 0.008, 0
swSketchMgr.CreateLine 0.07, 0.008, 0, 0.07, 0.018, 0

' ❌ 失败: 全部在表面上方 (Y=0.01~0.013, 表面 Y=0.01) → 草图与实体无交集
swSketchMgr.CreateLine 0.03, 0.01, 0, 0.04, 0.01, 0
swSketchMgr.CreateLine 0.04, 0.01, 0, 0.04, 0.013, 0
```

### 1.8 Edge 选择技巧

**Chamfer/Fillet 必须选中棱边，不能打到相邻面上**：

```vba
' ✅ 正确: 选 EDGE, Z 偏移避开表面 (棱边坐标只有一个变量匹配)
swModel.Extension.SelectByID2 "", "EDGE", 0.12, 0.01, 0.003, False, 0, Nothing, 0

' ❌ 失败: Z=0 时坐标落在圆柱面上, SelectByID2 选中 FACE 而非 EDGE
swModel.Extension.SelectByID2 "", "EDGE", 0.12, 0.01, 0, False, 0, Nothing, 0
```

### 1.9 参数边界扫描方法

```
Err=449 → 参数不够 (继续加)     Err=0   → 正确
Err=450 → 参数太多 (该减了)     Err=13  → 类型不匹配/API不存在
```

### 1.10 SW 2025 已知 Bug

| Bug | 影响 | 绕过方案 |
|-----|------|---------|
| `GetSelectedObjectCount2(-1)` 始终返回 0 | 无法验证选择是否成功 | 直接检查 Err.Number |
| `SelectByRay` 不存在 (Err=438) | 射线选择不可用 | 用 SelectByID2 选边/面 |
| `FeatureByName("Front Plane")` 返回 Nothing | 无法按英文名获取默认基准面 | 用 FirstFeature 遍历 |
| `GetDocumentTemplate` 不可用 | 无法编程新建文档 | 手动 Ctrl+N |

---

## 2. 已验证 API 签名 (7/7 全部调通)

### 2.1 InsertSketch2 — 插入草图

```vba
' SW 2025: 必须用 IModelDoc2.InsertSketch2 (ISketchManager.InsertSketch2 已废弃)
swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
swModel.InsertSketch2 True  ' True = 激活草图
' ... 画线 ...
' ⚠️ 不要再次调用 InsertSketch2 True 来关闭草图!
```

### 2.2 CreateLine / CreateCenterLine — 草图线段

```vba
' SW 2025 已重命名: CreateLine2→CreateLine, CreateCenterLine2→CreateCenterLine
swSketchMgr.CreateLine x1, y1, z1, x2, y2, z2       ' 米单位, Front Plane 必须 Z=0
swSketchMgr.CreateCenterLine x1, y1, z1, x2, y2, z2  ' 旋转中心线
```

### 2.3 FeatureRevolve2 — 旋转体/旋转切除 (20 参数)

```vba
' ⚠️ 必须在草图打开状态下调用!
' IsCut=False → 旋转建体, IsCut=True → 旋转切除

' === 旋转建体 ===
Set swFeat = swFeatMgr.FeatureRevolve2( _
    True,       ' SingleDir
    True,       ' IsSolid — True=实体, False=曲面
    False,      ' IsThin
    False,      ' IsCut — False=建体
    False,      ' ReverseDir
    False,      ' BothDirectionUpToSameEntity
    0, 0,       ' Dir1Type, Dir2Type
    6.28318530717958#, 0#,  ' Dir1Angle=360°, Dir2Angle
    False,      ' OffsetReverse1
    False,      ' OffsetReverse2
    0.01, 0.01, ' OffsetDistance1, OffsetDistance2
    0,          ' ThinType
    0#, 0#,     ' ThinThickness1, ThinThickness2
    True, True, True)       ' Merge, UseFeatScope, UseAutoSelect

' === 旋转切除 ===
Set swFeat = swFeatMgr.FeatureRevolve2( _
    True, True, False, _
    True,       ' IsCut — True=切除
    False, False, 0, 0, 6.28318530717958#, 0#, False, False, 0.01, 0.01, 0, 0#, 0#, True, True, True)
```

### 2.4 FeatureExtrusion2 — 拉伸凸台/切除 (23 参数)

```vba
' IsCut 通过 B1 和 D1/D2 的正负控制
' D1=0.005, D2=0.005 → 双向拉伸各 5mm, B2=True → 两侧对称

Set swFeat = swFeatMgr.FeatureExtrusion2( _
    True,       ' Sd — 单方向
    False,      ' Flip — 翻转方向
    False,      ' Dir — 方向
    0,          ' T1 — 终止类型
    0,          ' T2
    0.005,      ' D1 — 方向1距离 (米)
    0.005,      ' D2 — 方向2距离 (米)
    False,      ' Dchk1
    False,      ' Dchk2
    False,      ' Ddir1
    False,      ' Ddir2
    0#, 0#,     ' Dval1, Dval2
    False,      ' Dvalchk1
    False,      ' Dvalchk2
    0#, 0#,     ' Dvalval1, Dvalval2
    True,       ' B1 — 反向等距 (对称)
    True,       ' B2 — 方向2 开
    True,       ' Bcont
    False,      ' Boff
    0#,         ' Offset
    False)      ' Merge
```

### 2.5 FeatureExtrusion3 — 拉伸新版 (22 参数, SW2025)

```vba
' SW2025 新增 API, 参数比 Extrusion2 少 1 个
' D1,D2 参数位置靠后

Set swFeat = swFeatMgr.FeatureExtrusion3( _
    True,       ' Sd
    False,      ' Flip
    False,      ' Dir
    0, 0,       ' T1, T2
    0.005,      ' D1 — 方向1距离
    0.005,      ' D2 — 方向2距离
    False,      ' Dchk1
    False,      ' Dchk2
    False,      ' Ddir1
    False,      ' Ddir2
    0#, 0#,     ' Dval1, Dval2
    False,      ' Dvalchk1
    False,      ' Dvalchk2
    0#, 0#,     ' Dvalval1, Dvalval2
    False,      ' B1
    False,      ' B2
    False,      ' Bcont
    False,      ' Boff
    False, False)   ' 最后2参数
```

### 2.6 FeatureCut3 — 拉伸切除 (26 参数)

```vba
' SW2025 拉伸切除, 26 参数
' D1 控制切除深度, D2 控制反向深度

Set swFeat = swFeatMgr.FeatureCut3( _
    True,       ' Sd
    False,      ' Flip
    False,      ' Dir
    False,      ' T1Both
    0,          ' T1
    0.003,      ' D1 — 方向1切除深度 (米)
    False,      ' Dchk1 — 是否使用 D1
    0,          ' T2
    0.003,      ' D2 — 方向2切除深度 (米)
    False,      ' Dchk2
    False,      ' Ddir1
    0#, 0#,     ' Dval1, Dval2
    False,      ' Dvalchk1
    False,      ' Dvalchk2
    False,      ' Dvaldir1
    False,      ' Dvaldir2
    False,      ' Dvalval1
    True,       ' B1 — 反向等距
    True,       ' B2 — 方向2 开
    True,       ' Bcont
    False,      ' Boff
    0#,         ' Offset
    False,      ' Merge
    False,      ' FeatureScope
    False)      ' AutoSelect
```

### 2.7 InsertFeatureChamfer — 倒角 (8 参数)

```vba
' Type=1: 角度-距离模式
' Width=角度(弧度), 0.785=45°
' OtherDist=倒角值(米)
' ⚠️ 必须先选 EDGE (不能选 FACE), Z 偏移避开表面

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "EDGE", 0.12, 0.01, 0.003, False, 0, Nothing, 0

Set swFeat = Nothing: Err.Clear
Set swFeat = swFeatMgr.InsertFeatureChamfer( _
    1,          ' Type = 1 (角度-距离)
    1,          ' Options = 1
    0.785,      ' Width = 角度 (弧度, 0.785=45°)
    0.0015,     ' OtherDist = 倒角距离 (米)
    0#, 0#, 0#,  ' VertexChamDist (不用)
    False)      ' 最后一个参数
```

### 2.8 FeatureFillet3 — 圆角 (8 参数)

```vba
' ⚠️ Options=195 必须! (Options=0 或 1 均静默失败, 无论选 EDGE 还是 FACE)
' 选 EDGE: 坐标在棱边上 (Y 在凸台顶面, Z 偏移避开侧面)
' 选 FACE: 整面所有棱边倒圆角

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "EDGE", 0.06, 0.018, 0.005, False, 0, Nothing, 0

Set swFeat = Nothing: Err.Clear
Set swFeat = swFeatMgr.FeatureFillet3( _
    195,        ' Options — 必须 195! (1 和 0 都失败)
    0.001,      ' Radius1 (米)
    0, 0,       ' SetbackDist, SetbackType
    False,      ' TangentPropagation
    0,          ' OverflowType
    False,      ' FeatureScope
    False)      ' AutoSelect
```

### 2.9 InsertRefPlane — 创建参考基准面 (6 参数)

```vba
' ⚠️ SW 中文版必须用中文基准面名称!
' ConstraintType=8: 偏移距离
' 选择时必须 Append=True

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0

Set swPlane = Nothing: Err.Clear
Set swPlane = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
```

**约束类型常量**:

| 值 | 类型 | 说明 |
|----|------|------|
| 8 | Offset | 偏移距离 — **已验证可用** |
| 16 | Angle | 角度平面 (需两个平面选择) |
| 2 | Parallel | 平行 |
| 4 | Perpendicular | 垂直 |

### 2.10 SW 中文版基准面名称对照

| 英文 (API 文档) | 中文 (实际使用) |
|----------------|----------------|
| Front Plane | **前视基准面** |
| Top Plane | **上视基准面** |
| Right Plane | **右视基准面** |

```vba
' SelectByID2 草图选择: 两种写法都行
swModel.Extension.SelectByID2 "Front Plane", "PLANE", ...   ' ✅ 草图可用
swModel.Extension.SelectByID2 "前视基准面", "PLANE", ...      ' ✅ 草图可用

' InsertRefPlane 基准面创建: 只能中文!
swModel.Extension.SelectByID2 "前视基准面", "PLANE", ...      ' ✅ 创建成功!
swModel.Extension.SelectByID2 "Front Plane", "PLANE", ...    ' ❌ 返回 Nothing
```

---

## 3. 验证通过特征总结

| # | API | 参数数 | 用途 | 验证版本 | 状态 |
|---|-----|--------|------|---------|------|
| 0 | FeatureRevolve2 | 20 | 旋转建体 | v33 | ✅ PASS |
| 1 | FeatureExtrusion2 | 23 | 拉伸凸台 | v41 | ✅ PASS |
| 2 | FeatureRevolve2 (IsCut) | 20 | 旋转切除 | v41 | ✅ PASS |
| 3 | FeatureCut3 | 26 | 拉伸切除 | v41 | ✅ PASS |
| 4 | FeatureExtrusion3 | 22 | 拉伸新版 (SW2025) | v40 | ✅ PASS |
| 5 | InsertFeatureChamfer | 8 | 倒角 | v21 | ✅ PASS |
| 6 | FeatureFillet3 | 8 | 圆角 | v44 | ✅ PASS |

**v45 最终测试: 7/7 全部 PASS，完整阶梯轴模型创建成功**

---

## 4. 验证文件清单

| 文件 | 关键发现 |
|------|---------|
| `VerifySW2025_v21.bas` | 假阳性Bug修复 + Chamfer 正确签名 |
| `VerifySW2025_v23.bas` | Fillet Options=195 |
| `VerifySW2025_v28.bas` | GetSelectedObjectCount2(-1)=0 Bug 确认 |
| `VerifySW2025_v33.bas` | 中文名创建基准面成功 |
| `VerifySW2025_v34.bas` | 完整流程: 旋转+倒角+圆角+平面 |
| `VerifySW2025_v35~v38.bas` | 参数边界扫描: Extrusion2(23)/Extrusion3(22)/Cut3(26) |
| `VerifySW2025_v39.bas` | 草图打开状态验证, Ext2+RevolveCut 首次 PASS |
| `VerifySW2025_v40.bas` | Ext3=22 参数确认, Z=0 规则发现 |
| `VerifySW2025_v41.bas` | **突破**: Z=0 全适用, 7/8 PASS 含 Cut3(26) 首次成功 |
| `VerifySW2025_v42.bas` | 首次尝试完整阶梯轴 (失败: 草图悬空+选边错误) |
| `VerifySW2025_v43.bas` | 修复草图重叠和倒角选边, 6/7 PASS (仅 Fillet 失败) |
| `VerifySW2025_v44.bas` | Fillet 专项: EDGE+Options=195 确认, Options=1 确认失败 |
| `VerifySW2025_v45.bas` | **最终完整阶梯轴, 7/7 ALL PASS** ✨ |

---

## 5. 生产文件同步状态

| 文件 | 状态 | 备注 |
|------|------|------|
| `generate_sw_macro.py` | ⚠️ 待更新 | 仍用 CreateLine2, SelectByRay 等旧 API |
| `sw2025_create_shaft.py` | ⚠️ 待更新 | Python COM 驱动, 同上 |
| `CreateShaft_SW2025.bas` | ⚠️ 待更新 | 生成的宏含多处未验证 API |
| `create_shaft_macro.bas` | ⚠️ 待更新 | 旧版手写宏 |

> **下一步**: 将 v45 验证成果同步到生产文件。
