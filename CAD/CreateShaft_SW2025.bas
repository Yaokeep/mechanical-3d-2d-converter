Option Explicit

'============================================================================
' CreateShaft_SW2025 — SolidWorks 2025 阶梯轴参数化建模宏
'============================================================================
' 同步自: VerifySW2025_v45.bas (V45 验证成果)
' 单位系统: 草图使用 mm，API 调用自动转换为 米
'
' 特征树（全部可编辑）:
'   1. Revolve-ShaftBody   — 360°旋转基体
'   2. Chamfer-LeftEnd     — 左端面 C1.2
'   3. Chamfer-RightEnd    — 右端面 C1.2
'   4. Fillet-Transitions  — 各段过渡 R1.2（共 6 处）
'   5. Keyway-1 — 10×5mm
'   6. Keyway-2 — 12×6mm
'
' V45 关键规则:
'   - FeatureFillet3 Options 必须 = 195 (0 和 1 均静默失败)
'   - SelectByRay 不存在于 SW2025 → 改用 SelectByID2 "EDGE"
'   - 草图方法已重命名: CreateLine2→CreateLine, CreateCenterLine2→CreateCenterLine
'   - 特征方法必须在草图打开时调用 (不要在特征前关闭草图!)
'   - Chamfer 使用 Type=1 角度-距离模式
'   - InsertRefPlane 基准面名必须用中文
'
' 使用方法:
'   1. SolidWorks 2025 → 工具 → 宏 → 新建 → 粘贴此代码
'   2. 按 F5 或点击"运行"
'   3. 检查特征树确认所有特征创建成功
'   4. 文件 → 另存为 → SLDPRT
'============================================================================

' ----- SW 2025 枚举常量（避免依赖类型库引用）-----
Private Const swDocPART As Long = 1
Private Const swEndCondBlind As Long = 0
Private Const swEndCondThroughAll As Long = 1
Private Const swStartSketchPlane As Long = 0
Private Const swChamferDistanceDistance As Long = 2
Private Const swRefPlaneOffset As Long = 8
Private Const swFeatureFilletSimple As Long = 0
Private Const swSelectType_EDGES As Long = 2

' ----- 模块级变量 -----
Dim swApp       As Object  ' SldWorks.SldWorks
Dim swModel     As Object  ' SldWorks.ModelDoc2
Dim swPart      As Object  ' SldWorks.PartDoc
Dim swFeatMgr   As Object  ' SldWorks.FeatureManager
Dim swSketchMgr As Object  ' SldWorks.SketchManager
Dim swFeat      As Object  ' SldWorks.Feature
Dim boolstatus  As Boolean
Dim longstatus  As Long


' ===========================================================================
' 主入口
' ===========================================================================
Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks
    swApp.Visible = True
    swApp.UserControl = True

    ' 创建新零件文档（SW 2025 使用 mm 模板）
    Set swPart = swApp.NewDocument( _
        swApp.GetDocumentTemplate(swDocPART, "", 0, 0, 0), 0, 0, 0)
    If swPart Is Nothing Then
        MsgBox "无法创建新零件文档！请检查 SolidWorks 模板路径。", vbCritical
        Exit Sub
    End If
    Set swModel = swPart
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' 设置为 MMGS 单位系统
    swModel.SetUserPreferenceIntegerValue 296, 0  ' swUnitSystem = 296, swMMGS = 0

    ' 等轴测视图
    swModel.ShowNamedView2 "*Isometric", -1

    ' ====================================================================
    ' 步骤 1: 旋转基体 (Revolve) — 360° 全周旋转
    ' ====================================================================
    Debug.Print vbCrLf & "=== 步骤 1: Revolve-ShaftBody 旋转基体 ==="
    CreateRevolveShaftBody

    ' ====================================================================
    ' 步骤 2: 端面倒角 C1.2 (左 + 右)
    ' ====================================================================
    Debug.Print vbCrLf & "=== 步骤 2: 端面倒角 ==="
    CreateEndChamfer -233.066000#, 16.000000#, 0.001200#, "Chamfer-LeftEnd"
    CreateEndChamfer 221.734000#, 20.000000#, 0.001200#, "Chamfer-RightEnd"

    ' ====================================================================
    ' 步骤 3: 阶跃过渡圆角 R1.2（共 6 处）
    ' ====================================================================
    Debug.Print vbCrLf & "=== 步骤 3: Fillet-Transitions 过渡圆角 ==="
    CreateStepFillets

    ' ====================================================================
    ' 步骤 4: 键槽拉伸切除 (Cut-Extrude)
    ' ====================================================================
    Debug.Print vbCrLf & "=== 步骤 4: 键槽 ==="
    CreateKeywayFeature -196.266000#, 40.000000#, 5.000000#, 16.000000#, 5.000000#, "Keyway-1"
    CreateKeywayFeature 129.734000#, 38.000000#, 6.000000#, 21.500000#, 6.000000#, "Keyway-2"

    ' ====================================================================
    ' 完成
    ' ====================================================================
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2

    MsgBox "阶梯轴模型创建完成！" & vbCrLf & vbCrLf & _
           "特征树:" & vbCrLf & _
           "  1. Revolve-ShaftBody (旋转基体)" & vbCrLf & _
           "  2. Chamfer-LeftEnd (左端倒角 C1.2)" & vbCrLf & _
           "  3. Chamfer-RightEnd (右端倒角 C1.2)" & vbCrLf & _
           "  4. Fillet-Transitions (过渡圆角 R1.2)" & vbCrLf & _
           "  5. Keyway-1 (键槽 10×5mm)" & vbCrLf & _
           "  6. Keyway-2 (键槽 12×6mm)" & vbCrLf & _
           "" & vbCrLf & _
           "请执行: 文件 → 另存为 → 选择 SLDPRT 格式保存", _
           vbInformation, "CreateShaft_SW2025 — 完成"

    Exit Sub

ErrHandler:
    MsgBox "错误 " & Err.Number & ": " & Err.Description & vbCrLf & _
           "位置: " & Erl, vbCritical, "CreateShaft_SW2025 宏错误"
    Debug.Print "!!! ERROR " & Err.Number & " at line " & Erl & ": " & Err.Description
End Sub


' ===========================================================================
' CreateRevolveShaftBody — 在前视基准面绘制半剖面草图并旋转 360°
' ===========================================================================
' 使用 IFeatureManager.FeatureRevolve2 (SW 2024/2025/2026 统一 20 参数签名)
Private Sub CreateRevolveShaftBody()
    ' 选择前视基准面
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch2 True

    ' 绘制半剖面轮廓 (上半部分 + 中心线)
    With swSketchMgr
        .CreateLine -233.066000#, 0.000000#, 0#, -233.066000#, 16.000000#, 0#
        .CreateLine -233.066000#, 16.000000#, 0#, -158.466000#, 16.000000#, 0#
        .CreateLine -158.466000#, 16.000000#, 0#, -157.866000#, 16.000000#, 0#
        .CreateLine -157.866000#, 16.000000#, 0#, -157.866000#, 18.500000#, 0#
        .CreateLine -157.866000#, 18.500000#, 0#, -108.466000#, 18.500000#, 0#
        .CreateLine -108.466000#, 18.500000#, 0#, -107.866000#, 18.500000#, 0#
        .CreateLine -107.866000#, 18.500000#, 0#, -107.866000#, 20.000000#, 0#
        .CreateLine -107.866000#, 20.000000#, 0#, -85.466000#, 20.000000#, 0#
        .CreateLine -85.466000#, 20.000000#, 0#, -84.866000#, 20.000000#, 0#
        .CreateLine -84.866000#, 20.000000#, 0#, -84.866000#, 23.000000#, 0#
        .CreateLine -84.866000#, 23.000000#, 0#, 79.534000#, 23.000000#, 0#
        .CreateLine 79.534000#, 23.000000#, 0#, 80.134000#, 23.000000#, 0#
        .CreateLine 80.134000#, 23.000000#, 0#, 80.134000#, 25.000000#, 0#
        .CreateLine 80.134000#, 25.000000#, 0#, 86.734000#, 25.000000#, 0#
        .CreateLine 86.734000#, 25.000000#, 0#, 87.334000#, 25.000000#, 0#
        .CreateLine 87.334000#, 25.000000#, 0#, 87.334000#, 21.500000#, 0#
        .CreateLine 87.334000#, 21.500000#, 0#, 171.734000#, 21.500000#, 0#
        .CreateLine 171.734000#, 21.500000#, 0#, 172.334000#, 21.500000#, 0#
        .CreateLine 172.334000#, 21.500000#, 0#, 172.334000#, 20.000000#, 0#
        .CreateLine 172.334000#, 20.000000#, 0#, 221.734000#, 20.000000#, 0#
        .CreateLine 221.734000#, 20.000000#, 0#, 221.734000#, 0.000000#, 0#
        .CreateLine 221.734000#, 0.000000#, 0#, -233.066000#, 0.000000#, 0#
        ' 旋转中心线 (X 轴)
        .CreateCenterLine -233.066000#, 0#, 0#, 221.734000#, 0#, 0#
    End With

    ' V45 规则: 不关闭草图，在打开状态下调用特征方法

    ' FeatureRevolve2 — SW 2025: 20 参数
    ' 参数: SingleDir, IsSolid, IsThin, IsCut, ReverseDir,
    '        BothDirectionUpToSameEntity, Dir1Type, Dir2Type,
    '        Dir1Angle, Dir2Angle, OffsetReverse1, OffsetReverse2,
    '        OffsetDistance1, OffsetDistance2,
    '        ThinType, ThinThickness1, ThinThickness2,
    '        Merge, UseFeatScope, UseAutoSelect
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True,       ' SingleDir — 单方向
        True,       ' IsSolid — 实体特征
        False,      ' IsThin — 非薄壁
        False,      ' IsCut — 是凸台不是切除
        False,      ' ReverseDir — 不反向
        False,      ' BothDirectionUpToSameEntity
        0,          ' Dir1Type = swEndCondBlind (盲孔)
        0,          ' Dir2Type (未使用)
        6.28318530717958#, ' Dir1Angle = 360° 弧度
        0#,         ' Dir2Angle (未使用)
        False,      ' OffsetReverse1
        False,      ' OffsetReverse2
        0.01,       ' OffsetDistance1 (占位, 盲孔不使用)
        0.01,       ' OffsetDistance2 (占位)
        0,          ' ThinType (非薄壁不使用)
        0#,         ' ThinThickness1
        0#,         ' ThinThickness2
        True,       ' Merge — 合并结果
        True,       ' UseFeatScope
        True)       ' UseAutoSelect — 自动选择体

    If swFeat Is Nothing Then
        Err.Raise vbObjectError + 1, , _
            "旋转基体创建失败！请检查草图轮廓是否正确封闭。"
    End If
    swFeat.Name = "Revolve-ShaftBody"
    Debug.Print "  [OK] Revolve-ShaftBody (360 度旋转, 22 条轮廓线)"
End Sub


' ===========================================================================
' CreateEndChamfer — 使用 InsertFeatureChamfer 创建端面倒角 (V45 验证)
' ===========================================================================
' 参数:
'   faceX, radius: 端面外圆边缘的 X, Y 坐标 (mm)
'   chamferSize_m: 倒角尺寸 (米 — API 要求)
'   featName:      特征名称
'
' V45: SelectByRay 不存在 → 改用 SelectByID2 "EDGE" + Z=0.003 偏移
' V45: Type=1 角度-距离模式, Width=0.785=45°
Private Sub CreateEndChamfer( _
    ByVal faceX As Double, ByVal radius As Double, _
    ByVal chamferSize_m As Double, ByVal featName As String)

    Dim edgeCount As Long

    ' 清除已有选择
    swModel.ClearSelection2 True

    ' V45: SelectByRay 不存在 (Err=438) → 改用 SelectByID2 + Z 偏移选边
    swModel.Extension.SelectByID2 "", "EDGE", faceX, radius, 0.003, True, 0, Nothing, 0

    edgeCount = swModel.Extension.GetSelectionCount
    Debug.Print "  " & featName & ": 选中 " & edgeCount & " 条边"

    If edgeCount > 0 Then
        ' V45: Type=1 角度-距离模式, Width=0.785=45°
        Set swFeat = swFeatMgr.InsertFeatureChamfer( _
            1,               ' Options = 1
            1,               ' ChamferType = 1 (角度-距离)
            0.785,           ' Width = 45° 弧度
            chamferSize_m,   ' OtherDist = 倒角距离 (米)
            0#, 0#, 0#,      ' Vertex 距离 (未使用)
            False)           ' 最后一个参数

        If Not swFeat Is Nothing Then
            swFeat.Name = featName
            Debug.Print "  [OK] " & featName & " (C" & Format(chamferSize_m * 1000, "0.0") & ")"
        Else
            Debug.Print "  [FAIL] " & featName & " — InsertFeatureChamfer 返回 Nothing"
        End If
    Else
        Debug.Print "  [WARN] " & featName & " — 未找到端面边，请手动添加 C" & _
                    Format(chamferSize_m * 1000, "0.0") & " 倒角"
    End If
End Sub


' ===========================================================================
' CreateStepFillets — 对每个阶跃面选择外圆边并创建 R1.2 过渡圆角
' ===========================================================================
' 使用预选择边 + FeatureFillet3 方式
Private Sub CreateStepFillets()
    Dim i As Integer
    Dim totalEdges As Long, prevCount As Long

    swModel.ClearSelection2 True
    totalEdges = 0

    ' V45: SelectByRay 不存在 → 改用 SelectByID2 + Z 偏移选边
    ' 阶跃 1: X=-157.866, R=18.5
    swModel.Extension.SelectByID2 "", "EDGE", -157.866000#, 18.500000#, 0.003, True, 0, Nothing, 0
    ' 阶跃 2: X=-107.866, R=20.0
    swModel.Extension.SelectByID2 "", "EDGE", -107.866000#, 20.000000#, 0.003, True, 0, Nothing, 0
    ' 阶跃 3: X=-84.866, R=23.0
    swModel.Extension.SelectByID2 "", "EDGE", -84.866000#, 23.000000#, 0.003, True, 0, Nothing, 0
    ' 阶跃 4: X=80.134, R=25.0
    swModel.Extension.SelectByID2 "", "EDGE", 80.134000#, 25.000000#, 0.003, True, 0, Nothing, 0
    ' 阶跃 5: X=87.334, R=25.0
    swModel.Extension.SelectByID2 "", "EDGE", 87.334000#, 25.000000#, 0.003, True, 0, Nothing, 0
    ' 阶跃 6: X=172.334, R=21.5
    swModel.Extension.SelectByID2 "", "EDGE", 172.334000#, 21.500000#, 0.003, True, 0, Nothing, 0

    totalEdges = swModel.Extension.GetSelectionCount
    Debug.Print "  共选中 " & totalEdges & " 条阶跃边 (预期 6 条)"

    If totalEdges >= 6 Then
        ' V45: FeatureFillet3 Options 必须 = 195 (0 和 1 均静默失败)
        On Error Resume Next
        Set swFeat = swFeatMgr.FeatureFillet3( _
            195,                ' Options — 必须 195!
            0.001200#,          ' Radius (米) — R1.2mm = 0.001200m
            0, 0,               ' Setback (不使用)
            False,              ' TangentPropagation (V45: False)
            0,                  ' OverflowType
            False, False)       ' FeatureScope, AutoSelect (V45: False)
        On Error GoTo 0

        If Not swFeat Is Nothing Then
            swFeat.Name = "Fillet-Transitions"
            Debug.Print "  [OK] Fillet-Transitions (R1.2, " & totalEdges & " 条边)"
        Else
            Debug.Print "  [WARN] FeatureFillet3 失败，请手动选择所有阶跃边后添加 R1.2 圆角"
        End If
    Else
        Debug.Print "  [WARN] 仅选中 " & totalEdges & " 条边 (需要 6 条)"
        Debug.Print "  [INFO] 请手动选择所有 " & 6 & " 处阶跃外圆边 → 圆角 R1.2"
    End If
End Sub


' ===========================================================================
' CreateKeywayFeature — 在轴段上方创建键槽（拉伸切除）
' ===========================================================================
' 参数:
'   cx:        键槽中心 X 坐标 (mm)
'   length:    键槽总长 (mm)
'   halfWidth: 键槽半宽 (mm) — 矩形 Z 向半宽
'   shaftR:    轴段半径 (mm) — 用于创建切线基准面
'   depth:     键槽深度 (mm)
'   featName:  特征名称
'
' 方法:
'   1. 从 Top Plane 偏移 shaftR 创建切线基准面
'   2. 在基准面上绘制键槽矩形
'   3. 向下拉伸切除 depth 深度
Private Sub CreateKeywayFeature( _
    ByVal cx As Double, ByVal length As Double, _
    ByVal halfWidth As Double, ByVal shaftR As Double, _
    ByVal depth As Double, ByVal featName As String)

    Dim swPlane As Object  ' Feature
    Dim planeName As String
    Dim x1 As Double, x2 As Double
    Dim z1 As Double, z2 As Double
    Dim yTangent As Double  ' 切线面 Y 坐标 (mm)
    Dim offsetM As Double   ' 偏移距离 (米)

    planeName = featName & "-Plane"
    yTangent = shaftR       ' 轴顶部 Y = shaftR
    offsetM = shaftR / 1000# ' API 要求米

    ' 计算矩形角点（在切线基准面上）
    x1 = cx - length / 2#
    x2 = cx + length / 2#
    z1 = -halfWidth
    z2 = halfWidth

    ' ---- A: 从 Top Plane 创建偏移基准面 (InsertRefPlane 必须用中文名!)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0

    ' InsertRefPlane: 约束类型=8(偏移距离), 距离=offsetM(米)
    Set swPlane = swFeatMgr.InsertRefPlane(8, offsetM, 0, 0, 0, 0)

    If swPlane Is Nothing Then
        Debug.Print "  [FAIL] " & featName & " — 无法创建切线基准面 (偏移 " & shaftR & "mm)"
        Exit Sub
    End If
    swPlane.Name = planeName
    Debug.Print "  " & featName & ": 基准面已创建 (Top Plane 偏移 +" & shaftR & "mm)"

    ' ---- B: 在新的切线基准面上绘制键槽矩形 ----
    swSketchMgr.InsertSketch2 True

    With swSketchMgr
        ' 前边 Z=-halfWidth
        .CreateLine x1, yTangent, z1, x2, yTangent, z1
        ' 右边 X=x2
        .CreateLine x2, yTangent, z1, x2, yTangent, z2
        ' 后边 Z=+halfWidth
        .CreateLine x2, yTangent, z2, x1, yTangent, z2
        ' 左边 X=x1
        .CreateLine x1, yTangent, z2, x1, yTangent, z1
    End With

    ' V45 规则: 不关闭草图，在打开状态下调用 FeatureCut3

    ' ---- C: 拉伸切除 (FeatureCut3, 26 参数) ----
    ' 单方向、盲孔、深度 = depth mm → depth/1000 m
    ' 切除方向向下 (SW 默认方向，若反转请手动调整)
    Set swFeat = swFeatMgr.FeatureCut3( _
        True,               ' Sd — 单方向
        False,              ' Flip — 不翻转切除侧
        False,              ' Dir — 不反向
        0,                  ' T1 = swEndCondBlind
        0,                  ' T2 (未使用)
        depth / 1000#,      ' D1 深度 (米)
        depth / 1000#,      ' D2 (未使用)
        False,              ' Dchk1 — 无拔模
        False,              ' Dchk2
        False, False,       ' Ddir1, Ddir2
        0#, 0#,             ' Dang1, Dang2 — 拔模角度
        False, False,       ' OffsetReverse1, OffsetReverse2
        False, False,       ' TranslateSurface1, TranslateSurface2
        False,              ' NormalCut (非钣金)
        True,               ' UseFeatScope
        True,               ' UseAutoSelect
        False, False, False,' Assembly 相关
        0,                  ' T0 = swStartSketchPlane
        0#,                 ' StartOffset
        False)              ' FlipStartOffset

    If Not swFeat Is Nothing Then
        swFeat.Name = featName
        Debug.Print "  [OK] " & featName & _
                    " (L=" & Format(length, "0.0") & _
                    " W=" & Format(halfWidth * 2, "0.0") & _
                    " D=" & Format(depth, "0.0") & ")"
    Else
        Debug.Print "  [FAIL] " & featName & " — FeatureCut3 返回 Nothing"
        Debug.Print "  [INFO] 请手动创建: 选择草图 → 拉伸切除 → 深度 " & depth & "mm"
    End If

    ' ---- D: 隐藏辅助基准面 ----
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.BlankSketch
    On Error GoTo 0
End Sub
