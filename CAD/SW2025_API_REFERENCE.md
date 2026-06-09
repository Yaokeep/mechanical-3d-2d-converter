# SolidWorks 2025 (33.0.0) VBA API — 经验证参考

> 通过 30+ 轮递进验证宏确认的 SW 2025 API 正确调用方式。
> 验证日期: 2026-06-09

---

## 1. 核心编码规则

### 1.1 COM 晚期绑定 — 禁用括号语法

```vba
' ✅ 正确: 不用括号, 无返回值
swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0

' ❌ 错误: 用括号捕获返回值 — 可能返回 False (即使成功)
boolstatus = swModel.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
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

### 1.4 SW 2025 已知 Bug

| Bug | 影响 | 绕过方案 |
|-----|------|---------|
| `GetSelectedObjectCount2(-1)` 始终返回 0 | 无法验证选择是否成功 | 直接检查 Err.Number |
| `SelectByRay` 不存在 (Err=438) | 射线选择不可用 | 用 SelectByID2 选边/面 |
| `FeatureByName("Front Plane")` 返回 Nothing | 无法按英文名获取默认基准面 | 用 FirstFeature 遍历 |
| `GetDocumentTemplate` 不可用 | 无法编程新建文档 | 手动 Ctrl+N |

---

## 2. 已验证 API 签名

### 2.1 InsertSketch2 — 插入草图

```vba
' SW 2025: 必须用 IModelDoc2.InsertSketch2 (ISketchManager.InsertSketch2 已废弃)
swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
swModel.InsertSketch2 True  ' True = 激活草图
```

### 2.2 CreateLine / CreateCenterLine — 草图线段

```vba
' SW 2025 已重命名: CreateLine2→CreateLine, CreateCenterLine2→CreateCenterLine
swSketchMgr.CreateLine x1, y1, z1, x2, y2, z2       ' 米单位
swSketchMgr.CreateCenterLine x1, y1, z1, x2, y2, z2  ' 旋转中心线
```

### 2.3 FeatureRevolve2 — 旋转体 (20 参数)

```vba
' ⚠️ 必须在草图打开状态下调用! (不要在调用前 InsertSketch2 True 退出草图)
Set swFeat = swFeatMgr.FeatureRevolve2( _
    True,       ' SingleDir
    True,       ' IsSolid — True=实体, False=曲面
    False,      ' IsThin
    False,      ' IsCut
    False,      ' ReverseDir
    False,      ' BothDirectionUpToSameEntity
    0,          ' Dir1Type
    0,          ' Dir2Type
    6.28318530717958#,  ' Dir1Angle — 360° 弧度
    0#,         ' Dir2Angle
    False,      ' OffsetReverse1
    False,      ' OffsetReverse2
    0.01,       ' OffsetDistance1 (占位)
    0.01,       ' OffsetDistance2 (占位)
    0,          ' ThinType
    0#, 0#,     ' ThinThickness1, ThinThickness2
    True,       ' Merge
    True,       ' UseFeatScope
    True)       ' UseAutoSelect
```

### 2.4 InsertFeatureChamfer — 倒角 (8 参数)

```vba
' Type=1: 角度-距离模式
' Width=角度(弧度), 0.785=45°
' OtherDist=倒角值(米), 0.001=1mm
' 先用 SelectByID2 选边 (非 SelectByRay!)

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "EDGE", x, y, z, False, 0, Nothing, 0

Set swFeat = Nothing: Err.Clear
Set swFeat = swFeatMgr.InsertFeatureChamfer( _
    1,          ' Type = 1 (角度-距离)
    1,          ' Options = 1
    0.785,      ' Width = 角度 (弧度)
    0.001,      ' OtherDist = 倒角距离 (米)
    0#, 0#, 0#,  ' VertexChamDist (不用)
    False)      ' 最后一个参数
```

### 2.5 FeatureFillet3 — 圆角 (8 参数)

```vba
' ⚠️ Options=195 必须! (Options=0 会静默失败返回 Nothing)
' 先选面 (FACE)

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "FACE", x, y, z, False, 0, Nothing, 0

Set swFeat = Nothing: Err.Clear
Set swFeat = swFeatMgr.FeatureFillet3( _
    195,        ' Options — 必须 195!
    0.001,      ' Radius1 (米)
    0, 0,       ' SetbackDist, SetbackType
    False,      ' TangentPropagation
    0,          ' OverflowType
    False,      ' FeatureScope
    False)      ' AutoSelect
```

### 2.6 InsertRefPlane — 创建参考基准面 (6 参数)

```vba
' ⚠️ SW 中文版必须用中文基准面名称!
' ConstraintType=8: 偏移距离
' 选择时必须 Append=True

swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0

Set swPlane = Nothing: Err.Clear
Set swPlane = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
' 返回: 基准面1, 基准面2, ... (自动命名)
```

**约束类型常量**:

| 值 | 类型 | 说明 |
|----|------|------|
| 8 | Offset | 偏移距离 — **已验证可用** |
| 16 | Angle | 角度平面 (需两个平面选择) |
| 2 | Parallel | 平行 |
| 4 | Perpendicular | 垂直 |

### 2.7 SW 中文版基准面名称对照

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

## 3. 未解决问题

| 问题 | 状态 | 错误 |
|------|------|------|
| FeatureCut3 | ❌ 失败 | Err=13 类型不匹配 |
| FeatureCut4 | ❌ 失败 | Err=449 参数不够 |
| FeatureCut5 | ❌ 未测试 | — |
| FeatureCut (19参) | ❌ 失败 | Err=13 |
| FeatureExtrusion3 | ❌ 失败 | Err=13 |
| SelectByRay | ❌ 不存在 | Err=438 |
| GetDocumentTemplate | ❌ 不可用 | — |

### 键槽切除的替代方案

由于 FeatureCut3 尚未调通，键槽切除可考虑：
1. **Top Plane 直接切除** — 在 Top Plane 上画键槽草图, 向下切除 (无需新基准面)
2. **基准面 + 手动切除** — 用已验证的 InsertRefPlane 创建平面, 手动执行切除
3. **FeatureExtrusion2 待测试** — 可能需要其他参数组合

---

## 4. 验证文件清单

| 文件 | 状态 | 关键发现 |
|------|------|---------|
| `verify_log/VerifySW2025_v8.bas` | 历史 | FeatureRevolve2: 草图必须打开 |
| `verify_log/VerifySW2025_v9.bas` | 历史 | IsSolid=True 生成实体 |
| `verify_log/VerifySW2025_v21.bas` | 历史 | 假阳性Bug修复 + 倒角正确签名 |
| `verify_log/VerifySW2025_v23.bas` | 历史 | 圆角 Options=195 |
| `verify_log/VerifySW2025_v28.bas` | 历史 | GetSelectedObjectCount2(-1)=0 Bug 确认 |
| `VerifySW2025_v33.bas` | ✨ | **中文名创建基准面成功** |
| `VerifySW2025_v34.bas` | ✨ | 完整流程: 旋转+倒角+圆角+平面+切除测试 |

---

## 5. 生产文件同步状态

| 文件 | 状态 | 备注 |
|------|------|------|
| `generate_sw_macro.py` | ⚠️ 待更新 | 仍用 CreateLine2, SelectByRay 等旧 API |
| `sw2025_create_shaft.py` | ⚠️ 待更新 | Python COM 驱动, 同上 |
| `CreateShaft_SW2025.bas` | ⚠️ 待更新 | 生成的宏含多处未验证 API |
| `create_shaft_macro.bas` | ⚠️ 待更新 | 旧版手写宏 |

> **暂不更新生产文件** — 等 FeatureCut 调通后再统一同步所有发现。
