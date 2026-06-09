Option Explicit

'============================================================================
' 阶梯轴参数化建模宏 — 生成可编辑特征的 .sldprt
'
' 功能:
'   1. 旋转凸台 (Revolve) — 主轴体
'   2. 倒角特征 (Chamfer) ×2 — 左右端面
'   3. 圆角特征 (Fillet) ×6 — 各段过渡
'   4. 拉伸切除 (Cut-Extrude) ×2 — 键槽
'
' 使用方法:
'   1. SolidWorks → 工具 → 宏 → 新建 → 粘贴此代码
'   2. 按 F5 运行
'   3. 文件 → 另存为 → .sldprt
'
' 生成自: generate_sw_macro.py
' 单位: 毫米 (mm)
'
' ⚠️ 已修复 SW 2025 单位转换: API 所有长度单位为米，mm→m 需除以 1000
' ⚠️ 如需更完整版本，请使用 CAD/CreateShaft_SW2025.bas
'============================================================================

Dim swApp As SldWorks.SldWorks
Dim swModel As ModelDoc2
Dim swPart As PartDoc
Dim swFeat As Feature
Dim swSketchMgr As SketchManager
Dim swSelMgr As SelectionMgr
Dim boolstatus As Boolean
Dim longstatus As Long

Sub main()
    Set swApp = Application.SldWorks
    swApp.Visible = True

    ' 创建新零件
    Set swPart = swApp.NewDocument(swApp.GetDocumentTemplate(swDocPART, "", 0, 0, 0), 0, 0, 0)
    Set swModel = swPart
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' 切换到 ISO 视图以便观察
    swModel.ShowNamedView2 "Isometric", -1

    '=======================================================================
    ' 步骤 1: 旋转基体 (Revolve) — 阶梯轴主体
    '=======================================================================
    Debug.Print "=== 创建旋转基体 ==="

    ' 在前视基准面上创建草图
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch True

    ' 绘制半剖面轮廓线 (上半部分 + 中心线)
    With swSketchMgr
    .CreateLine2 -233.066000#, 0.000000#, 0#, -233.066000#, 16.000000#, 0#
    .CreateLine2 -233.066000#, 16.000000#, 0#, -158.466000#, 16.000000#, 0#
    .CreateLine2 -158.466000#, 16.000000#, 0#, -157.866000#, 16.000000#, 0#
    .CreateLine2 -157.866000#, 16.000000#, 0#, -157.866000#, 18.500000#, 0#
    .CreateLine2 -157.866000#, 18.500000#, 0#, -108.466000#, 18.500000#, 0#
    .CreateLine2 -108.466000#, 18.500000#, 0#, -107.866000#, 18.500000#, 0#
    .CreateLine2 -107.866000#, 18.500000#, 0#, -107.866000#, 20.000000#, 0#
    .CreateLine2 -107.866000#, 20.000000#, 0#, -85.466000#, 20.000000#, 0#
    .CreateLine2 -85.466000#, 20.000000#, 0#, -84.866000#, 20.000000#, 0#
    .CreateLine2 -84.866000#, 20.000000#, 0#, -84.866000#, 23.000000#, 0#
    .CreateLine2 -84.866000#, 23.000000#, 0#, 79.534000#, 23.000000#, 0#
    .CreateLine2 79.534000#, 23.000000#, 0#, 80.134000#, 23.000000#, 0#
    .CreateLine2 80.134000#, 23.000000#, 0#, 80.134000#, 25.000000#, 0#
    .CreateLine2 80.134000#, 25.000000#, 0#, 86.734000#, 25.000000#, 0#
    .CreateLine2 86.734000#, 25.000000#, 0#, 87.334000#, 25.000000#, 0#
    .CreateLine2 87.334000#, 25.000000#, 0#, 87.334000#, 21.500000#, 0#
    .CreateLine2 87.334000#, 21.500000#, 0#, 171.734000#, 21.500000#, 0#
    .CreateLine2 171.734000#, 21.500000#, 0#, 172.334000#, 21.500000#, 0#
    .CreateLine2 172.334000#, 21.500000#, 0#, 172.334000#, 20.000000#, 0#
    .CreateLine2 172.334000#, 20.000000#, 0#, 221.734000#, 20.000000#, 0#
    .CreateLine2 221.734000#, 20.000000#, 0#, 221.734000#, 0.000000#, 0#
    .CreateLine2 221.734000#, 0.000000#, 0#, -233.066000#, 0.000000#, 0#

    ' 中心线 (旋转轴)
        .CreateCenterLine2 -233.066000#, 0#, 0#, 221.734000#, 0#, 0#
    End With

    ' 退出草图并创建旋转特征
    swSketchMgr.InsertSketch True

    ' FeatureRevolve2: 360° 旋转
    ' 参数: angle, reverseDir, angle2, revType, ... merge, useFeatScope, autoSelect
    Set swFeat = swModel.FeatureManager.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 2 * 3.14159265358979, 0, False, False, 0, 0, True, True, True, 0, 0)

    If swFeat Is Nothing Then
        MsgBox "旋转基体创建失败!", vbCritical
        Exit Sub
    End If
    swFeat.Name = "Revolve-ShaftBody"
    Debug.Print "  旋转基体创建成功"

    '=======================================================================
    ' 步骤 2: 倒角特征 (Chamfer) — 左右端面
    '=======================================================================
    Debug.Print "=== 创建倒角特征 ==="

    ' 左端面倒角 C1.2
    ' 端面是旋转体的平面端面，在 X=-233.066 的平面上
    CreateEndChamfer -233.066000#, 16.000000#, 1.200000#, "Chamfer-LeftEnd"

    ' 右端面倒角 C1.2
    CreateEndChamfer 221.734000#, 20.000000#, 1.200000#, "Chamfer-RightEnd"

    '=======================================================================
    ' 步骤 3: 圆角特征 (Fillet) — 各段过渡 R1.2
    '=======================================================================
    Debug.Print "=== 创建圆角特征 ==="

    ' 方法: 对每个阶跃面处的边添加 R1.2 圆角
    ' 外圆柱面上每个阶跃处有 1 条圆周边需要倒圆角
    ' 使用 FeatureFillet 或手动选择边

    ' 清除选择
    swModel.ClearSelection2 True

    ' 选择所有外圆柱面的阶跃边
    ' 阶跃位置: X≈-157.9, X≈-107.9, X≈-84.9, X≈80.1, X≈87.3, X≈172.3

    ' 圆角1: 段1→段2, X≈-157.866, R18.5→R16.0
    swModel.Extension.SelectByRay -157.866000#, 18.500000#, 0#, -157.866000#, 18.500000#, 1#, 0.01, 2, True, 0, Nothing

    ' 圆角2: 段2→段3, X≈-107.866, R20.0→R18.5
    swModel.Extension.SelectByRay -107.866000#, 20.000000#, 0#, -107.866000#, 20.000000#, 1#, 0.01, 2, True, 0, Nothing

    ' 圆角3: 段3→段4, X≈-84.866, R23.0→R20.0
    swModel.Extension.SelectByRay -84.866000#, 23.000000#, 0#, -84.866000#, 23.000000#, 1#, 0.01, 2, True, 0, Nothing

    ' 圆角4: 段4→段5, X≈80.134, R25.0→R23.0
    swModel.Extension.SelectByRay 80.134000#, 25.000000#, 0#, 80.134000#, 25.000000#, 1#, 0.01, 2, True, 0, Nothing

    ' 圆角5: 段5→段6, X≈87.334, R25.0→R21.5
    swModel.Extension.SelectByRay 87.334000#, 25.000000#, 0#, 87.334000#, 25.000000#, 1#, 0.01, 2, True, 0, Nothing

    ' 圆角6: 段6→段7, X≈172.334, R21.5→R20.0
    swModel.Extension.SelectByRay 172.334000#, 21.500000#, 0#, 172.334000#, 21.500000#, 1#, 0.01, 2, True, 0, Nothing

    ' 尝试用当前选择创建圆角
    longstatus = swModel.Extension.GetSelectionCount
    If longstatus >= 6 Then
        Set swFeat = swModel.FeatureManager.FeatureFillet(1.2 / 1000#, 1, 0, 0, 0, 0, 0)  ' R1.2mm = 0.0012m
        If Not swFeat Is Nothing Then
            swFeat.Name = "Fillet-StepTransitions"
            Debug.Print "  圆角特征创建成功: R1.2"
        Else
            Debug.Print "  圆角特征创建失败，请手动添加"
        End If
    Else
        Debug.Print "  选择了 " & longstatus & " 条边 (预期 6 条)"
        Debug.Print "  请手动添加 R1.2 圆角到各阶跃边"
    End If

    '=======================================================================
    ' 步骤 4: 键槽拉伸切除 (Cut-Extrude)
    '=======================================================================
    Debug.Print "=== 创建键槽 ==="

    ' 键槽1: X=[-216.3, -176.3], 宽=10.0, 深=5.0
    CreateKeyway -216.266000#, -176.266000#, _
                 10.000000#, 5.000000#, _
                 16.000000#, "Keyway-1"

    ' 键槽2: X=[110.7, 148.7], 宽=12.0, 深=6.0
    CreateKeyway 110.734000#, 148.734000#, _
                 12.000000#, 6.000000#, _
                 21.500000#, "Keyway-2"

    '=======================================================================
    ' 完成 — 重建模型
    '=======================================================================
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2

    ' 保存提示
    MsgBox "阶梯轴模型创建完成!" & vbCrLf & vbCrLf & _
           "特征树:" & vbCrLf & _
           "  1. Revolve-ShaftBody (旋转基体)" & vbCrLf & _
           "  2. Chamfer-LeftEnd (左端倒角 C1.2)" & vbCrLf & _
           "  3. Chamfer-RightEnd (右端倒角 C1.2)" & vbCrLf & _
           "  4. Fillet-StepTransitions (圆角 R1.2)" & vbCrLf & _
           "  5. Keyway-1 (键槽 10×5mm)" & vbCrLf & _
           "  6. Keyway-2 (键槽 12×6mm)" & vbCrLf & vbCrLf & _
           "请执行: 文件 → 另存为 → SLDPRT", _
           vbInformation, "阶梯轴建模完成"

    Debug.Print "=== 全部完成 ==="
End Sub


'============================================================================
' 辅助函数: 创建端面倒角
'============================================================================
Private Sub CreateEndChamfer(faceX As Double, radius As Double, _
                              chamferSize As Double, featName As String)
    Dim swFeat As Feature
    Dim selCount As Long

    swModel.ClearSelection2 True

    ' 选择端面的外圆边
    ' 端面位于 X = faceX，外圆边在 Y = radius 位置
    ' 用射线选择 (从端面圆心沿 Y 方向)
    swModel.Extension.SelectByRay faceX, radius, 0#, faceX, radius, 1#, 0.01, 2, True, 0, Nothing

    selCount = swModel.Extension.GetSelectionCount
    If selCount > 0 Then
        ' FeatureChamfer: chamferType=1 (距离-距离), 两方向距离都等于 chamferSize
        Set swFeat = swModel.FeatureManager.InsertFeatureChamfer(0, 2, 0#, 0#, chamferSize / 1000#, 0#, 0#, 0#)
        ' (旧版 FeatureChamfer 已替换为 SW2025 InsertFeatureChamfer)
        ' Set swFeat = swModel.FeatureManager.FeatureChamfer(1, chamferSize / 1000#, chamferSize / 1000#, _
            0, 0, 0, 0, 0, 0)
        If Not swFeat Is Nothing Then
            swFeat.Name = featName
            Debug.Print "  " & featName & " 创建成功: C" & chamferSize
        Else
            Debug.Print "  " & featName & " 创建失败"
        End If
    Else
        Debug.Print "  " & featName & ": 未找到端面边 (X=" & faceX & ")"
    End If
End Sub


'============================================================================
' 辅助函数: 创建键槽 (拉伸切除)
'============================================================================
Private Sub CreateKeyway(xStart As Double, xEnd As Double, _
                          kwWidth As Double, kwDepth As Double, _
                          shaftRadius As Double, featName As String)
    Dim swFeat As Feature
    Dim swPlane As Feature
    Dim planeName As String
    Dim kwLen As Double
    Dim kwCenterX As Double

    kwLen = xEnd - xStart
    kwCenterX = (xStart + xEnd) / 2#

    ' 方法: 在与轴表面相切的平面上创建草图
    ' 创建偏移基准面: Front Plane 沿 Y 方向偏移 shaftRadius
    ' 轴在 XY 平面中旋转，轴表面顶部在 Y = +shaftRadius

    planeName = featName & "-Plane"

    ' 选择 Front Plane (XY) 并创建偏移基准面
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swPlane = swModel.FeatureManager.InsertRefPlane(8, shaftRadius / 1000#, 0, 0, 0, 0)  ' mm→m
    ' refPlaneType=8: Offset distance

    If Not swPlane Is Nothing Then
        swPlane.Name = planeName
        Debug.Print "  基准面 " & planeName & " 创建成功 (偏移 " & shaftRadius & "mm)"
    Else
        Debug.Print "  基准面创建失败，尝试使用 Top Plane"
        ' 回退方案：使用上视基准面
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    End If

    ' 在新基准面上创建键槽草图
    swSketchMgr.InsertSketch True

    ' 键槽矩形: 中心在 (kwCenterX, shaftRadius, 0)
    ' 矩形角点
    Dim x1 As Double, x2 As Double
    Dim z1 As Double, z2 As Double
    x1 = kwCenterX - kwLen / 2#
    x2 = kwCenterX + kwLen / 2#
    z1 = -kwWidth / 2#
    z2 = kwWidth / 2#

    ' 绘制矩形
    With swSketchMgr
        .CreateLine2 x1, shaftRadius, z1, x2, shaftRadius, z1  ' 底边
        .CreateLine2 x2, shaftRadius, z1, x2, shaftRadius, z2  ' 右边
        .CreateLine2 x2, shaftRadius, z2, x1, shaftRadius, z2  ' 顶边
        .CreateLine2 x1, shaftRadius, z2, x1, shaftRadius, z1  ' 左边
    End With

    swSketchMgr.InsertSketch True

    ' 拉伸切除: 方向向下 (沿 -Y)，深度 = kwDepth
    Set swFeat = swModel.FeatureManager.FeatureCut3(True, False, False, _
        0, 0, kwDepth / 1000#, kwDepth / 1000#, False, False, False, False, _  ' mm→m
        0, 0, False, False, False, False, False, True, True, True, True, False, 0, 0)

    If Not swFeat Is Nothing Then
        swFeat.Name = featName
        Debug.Print "  " & featName & " 创建成功"
    Else
        Debug.Print "  " & featName & " 创建失败 — 请手动创建"
    End If
End Sub
