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

# ---- 倒角类型 ----
swChamferDistanceDistance = 2  # 等距倒角

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
