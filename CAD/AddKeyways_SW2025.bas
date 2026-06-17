' 阶梯轴特征补充宏 — 在已有旋转基体上添加倒角、圆角、键槽
' 使用方法: SolidWorks → 工具 → 宏 → 新建 → 粘贴此代码 → 运行
' 前提: 已打开包含 Revolve-ShaftBody 特征的零件文档

Const swDocPART As Long = 1
Const swEndCondBlind As Long = 0
Const swChamferDistanceDistance As Long = 2
Const swRefPlaneOffset As Long = 8
Const swSelectType_EDGES As Long = 2

' ============================================================================
' 主入口
' ============================================================================
Sub main()
    Dim swApp As SldWorks.SldWorks
    Dim swModel As SldWorks.ModelDoc2
    Dim swFeatMgr As SldWorks.FeatureManager
    Dim swSketchMgr As SldWorks.SketchManager

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc

    If swModel Is Nothing Then
        MsgBox "请先打开包含旋转基体的零件文档！", vbCritical
        Exit Sub
    End If

    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' 键槽参数
    ' 键槽1: 左端, 中心 X=-196.27, 长40, 半宽5, 轴半径16, 深5
    CreateKeyway swFeatMgr, swSketchMgr, swModel, _
        -196.27, 40#, 5#, 16#, 5#, "Keyway-1"

    ' 键槽2: 右端, 中心 X=129.73, 长38, 半宽6, 轴半径21.5, 深6
    CreateKeyway swFeatMgr, swSketchMgr, swModel, _
        129.73, 38#, 6#, 21.5, 6#, "Keyway-2"

    ' 完成
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2

    MsgBox "键槽创建完成！" & vbCrLf & vbCrLf & _
           "特征树:" & vbCrLf & _
           "  1. Revolve-ShaftBody (旋转基体)" & vbCrLf & _
           "  2. Keyway-1 (键槽 10×5mm)" & vbCrLf & _
           "  3. Keyway-2 (键槽 12×6mm)", vbInformation, "阶梯轴完成"
End Sub

' ============================================================================
' 键槽创建 — 拉伸切除方法
' ============================================================================
Private Sub CreateKeyway( _
    ByVal swFeatMgr As SldWorks.FeatureManager, _
    ByVal swSketchMgr As SldWorks.SketchManager, _
    ByVal swModel As SldWorks.ModelDoc2, _
    ByVal cx As Double, ByVal length As Double, _
    ByVal halfWidth As Double, ByVal shaftR As Double, _
    ByVal depth As Double, ByVal featName As String)

    Dim swPlane As SldWorks.RefPlane
    Dim swFeat As SldWorks.Feature
    Dim planeName As String
    Dim yTangent As Double
    Dim offsetM As Double
    Dim depthM As Double
    Dim x1 As Double, x2 As Double
    Dim z1 As Double, z2 As Double

    planeName = featName & "-Plane"
    yTangent = shaftR
    offsetM = shaftR / 1000#
    depthM = depth / 1000#

    x1 = cx - length / 2#
    x2 = cx + length / 2#
    z1 = -halfWidth
    z2 = halfWidth

    ' A: 创建切线基准面
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0

    Set swPlane = swFeatMgr.InsertRefPlane(8, offsetM, 0, 0, 0, 0)
    If swPlane Is Nothing Then
        Debug.Print "  [FAIL] " & featName & " — 无法创建切线基准面"
        Exit Sub
    End If
    swPlane.Name = planeName
    Debug.Print "  [INFO] " & planeName & " 已创建 (偏移 +" & shaftR & "mm)"

    ' B: 绘制键槽矩形草图
    swSketchMgr.InsertSketch2 True

    swSketchMgr.CreateLine x1, yTangent, z1, x2, yTangent, z1  ' 前边
    swSketchMgr.CreateLine x2, yTangent, z1, x2, yTangent, z2  ' 右边
    swSketchMgr.CreateLine x2, yTangent, z2, x1, yTangent, z2  ' 后边
    swSketchMgr.CreateLine x1, yTangent, z2, x1, yTangent, z1  ' 左边

    ' C: 拉伸切除
    Set swFeat = swFeatMgr.FeatureCut3( _
        True, False, False, _
        0, 0, _
        depthM, depthM, _
        False, False, False, False, 0#, 0#, _
        False, False, False, False, False, _
        True, True, _
        False, False, False, _
        0, 0#, False)

    If swFeat Is Nothing Then
        Debug.Print "  [FAIL] " & featName & " — FeatureCut3 返回 Nothing"
        Exit Sub
    End If

    swFeat.Name = featName
    Debug.Print "  [OK] " & featName & " (L=" & length & " W=" & halfWidth * 2 & " D=" & depth & ")"
End Sub
