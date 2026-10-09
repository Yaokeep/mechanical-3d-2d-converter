# SolidWorks 2025 API 枚举常量
# 来源: 经验证确认的 SW 2025 (33.0.0) 晚期绑定常数值
# 参考: ../../../CAD/SW2025_API_REFERENCE.md

# ---- 文档类型 ----
swDocPART = 1          # 零件文档
swDocASSEMBLY = 2      # 装配体文档
swDocDRAWING = 3       # 工程图文档

# ---- 终止条件 ----
swEndCondBlind = 0      # 盲孔（给定深度）
swEndCondThroughAll = 1 # 完全贯穿

# ---- 草图基准面类型 ----
swStartSketchPlane = 0  # 草图起始于基准面

# ---- 基准面约束类型 ----
swRefPlaneOffset = 8    # 偏移距离约束
# 偏移"翻向"位（= 8 | 256）。**必须与距离约束相加**：单用 256、或错配 128
# （那是 mid-plane 位）都会让 InsertRefPlane 返回 None（2026-09-28 实测）。
# 用途：SW 的 InsertRefPlane **吃不下负距离**——传 −50 会静默把面建在 0 处
# （_probe_sw_negplane.py 实测：−50 → SW y=0、−110 → SW z=0）。要做负侧的
# 面只能"正距离 + 翻向位"：上视 +50/264 → SW y=−50、前视 +110/264 → z=−110 ✓
swRefPlaneOffsetFlip = 8 + 256

# ---- 倒角类型 ----
swChamferDistanceDistance = 2  # 等距倒角

# ---- 回转终止条件（FeatureRevolve2 的 Dir1Type）----
# 2026-10-10 实测（根目录 `_probe_sw_revmid.py`，前视面上画 centerline + 矩形
# (3,0)-(5,4) 按 Dir1Type×角度 试建量体积）：
#   Dir1Type=6 角 90° → 体积 50.27（= 201.06/4）、bbox z ±3.536 = ±5·sin45°
#     → **两侧对称中面，Dir1Angle = 总角**
#   Dir1Type=7 角 90° → 体积同为 50.27 但 bbox z∈[−5,0] → 单侧扫，**不是**中面
# （曾按网上枚举表猜 7 = MidPlane，实测推翻；以本行实测值为准。）
# 用途：bracket #6 根部圆角的角域 ±57.78° 回转补料（SW 原生圆角无角域限制）。
swEndCondMidPlane = 6

# ---- 圆角类型 ----
# V45 验证: SW2025 FeatureFillet3 必须 Options=195 (0 和 1 均静默失败)
swFeatureFilletSimple = 0      # 等半径圆角 (SW2025 不可用!)
SW_FILLET_OPTIONS = 195        # SW2025 FeatureFillet3 唯一可用值

# ---- 选择类型 ----
swSelectType_FACES = 1   # 面选择
swSelectType_EDGES = 2   # 边选择

# ---- 保存选项 ----
swSaveAsCurrentVersion = 0  # 当前版本格式
swSaveAsOptions_Silent = 1  # 静默保存（不显示对话框）

# ---- 单位系统 ----
# swUnitSystem = 296, swMMGS = 0
SW_USER_PREF_UNIT_SYSTEM = 296
swMMGS = 0  # 毫米-克-秒
