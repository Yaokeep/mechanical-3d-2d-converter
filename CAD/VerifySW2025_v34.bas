Option Explicit

' VerifySW2025 v34 - 利用中文名基准面 + 完整切除流程
' 关键发现: SW中文版必须用 "前视基准面" 而非 "Front Plane" 来创建基准面!

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swPlaneFeat As Object
Dim boolstatus As Boolean, featBefore As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    Debug.Print "初始特征数: " & swModel.GetFeatureCount

    ' ==================================================================
    ' 步骤1: 旋转体 (已知可行)
    ' ==================================================================
    Debug.Print vbCrLf & "=== 步骤1: 旋转体 ==="
    On Error Resume Next

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 简单圆柱: 半径10mm, 长50mm, 绕X轴
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0

    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL Err=" & Err.Number, "PASS")

    If swFeat Is Nothing Then MsgBox "旋转体创建失败!", vbCritical: Exit Sub

    ' ==================================================================
    ' 步骤2: 倒角+圆角 (验证过的)
    ' ==================================================================
    Debug.Print vbCrLf & "=== 步骤2: 倒角+圆角 ==="

    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "", "EDGE", 0.05, 0.01, 0, False, 0, Nothing, 0
    Debug.Print "选边(倒角): Err=" & Err.Number
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "FAIL Err=" & Err.Number, "PASS")

    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "", "FACE", 0.04, 0.005, 0.01, False, 0, Nothing, 0
    Debug.Print "选面(圆角): Err=" & Err.Number
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "FAIL Err=" & Err.Number, "PASS")

    ' ==================================================================
    ' 步骤3: 创建偏移基准面 (中文名!)
    ' 在圆柱顶部上方10mm处创建平面用于键槽切除
    ' ==================================================================
    Debug.Print vbCrLf & "=== 步骤3: 创建基准面 ==="

    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Debug.Print "选上视基准面: Err=" & Err.Number

    Set swPlaneFeat = Nothing: Err.Clear
    Set swPlaneFeat = swFeatMgr.InsertRefPlane(8, 0.012, 0, 0, 0, 0)
    Debug.Print "偏移平面(12mm): " & IIf(swPlaneFeat Is Nothing, "Nothing", swPlaneFeat.Name) & " Err=" & Err.Number

    ' 如果成功, 保存平面名用于后续选择
    Dim planeName As String
    If Not swPlaneFeat Is Nothing Then
        planeName = swPlaneFeat.Name
        Debug.Print "  ★ 平面创建成功: " & planeName
    Else
        Debug.Print "  ★ 平面创建失败! 将直接在Top Plane上切除"
        planeName = "上视基准面"
    End If

    On Error GoTo ErrHandler

    ' ==================================================================
    ' 步骤4: FeatureCut — 逐个尝试, 每步独立
    ' ==================================================================
    Debug.Print vbCrLf & "=== 步骤4: FeatureCut 测试 ==="
    On Error Resume Next

    ' C1: FeatureCut3 — 26参数, 盲孔5mm
    Debug.Print "--- C1: Cut3(26) 盲孔5mm ---"
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  选平面'" & planeName & "': Err=" & Err.Number
    swModel.InsertSketch2 True

    ' 键槽矩形: X=15-35mm, Z=-4~4mm (宽8mm)
    swSketchMgr.CreateLine 0.015, 0, -0.004, 0.035, 0, -0.004
    swSketchMgr.CreateLine 0.035, 0, -0.004, 0.035, 0, 0.004
    swSketchMgr.CreateLine 0.035, 0, 0.004, 0.015, 0, 0.004
    swSketchMgr.CreateLine 0.015, 0, 0.004, 0.015, 0, -0.004

    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.005, False, 0, 0.005, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False, Nothing, False)
    Debug.Print "  C1结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C2: FeatureCut3 — ThroughAll, 退出草图后
    Debug.Print "--- C2: Cut3(26) ThroughAll 退出草图 ---"
    swModel.InsertSketch2 True  ' 退出草图
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.005, False, 0, 0.005, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False, Nothing, False)
    Debug.Print "  C2结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C3: FeatureCut3 — 草图打开状态, 22参数(少4个)
    Debug.Print "--- C3: Cut3(22) 草图打开 ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0, -0.004, 0.035, 0, -0.004
    swSketchMgr.CreateLine 0.035, 0, -0.004, 0.035, 0, 0.004
    swSketchMgr.CreateLine 0.035, 0, 0.004, 0.015, 0, 0.004
    swSketchMgr.CreateLine 0.015, 0, 0.004, 0.015, 0, -0.004
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.005, False, 0, 0.005, False, False, 0#, False, 0#, False, 0#, False, 0#, False, False)
    Debug.Print "  C3结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C4: FeatureCut (不带数字) — 19参数
    Debug.Print "--- C4: FeatureCut(19) 退出草图 ---"
    swModel.InsertSketch2 True
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, False, False, False, False)
    Debug.Print "  C4结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C5: FeatureCut4 — 22参数, 草图打开
    Debug.Print "--- C5: Cut4(22) 草图打开 ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0, -0.004, 0.035, 0, -0.004
    swSketchMgr.CreateLine 0.035, 0, -0.004, 0.035, 0, 0.004
    swSketchMgr.CreateLine 0.035, 0, 0.004, 0.015, 0, 0.004
    swSketchMgr.CreateLine 0.015, 0, 0.004, 0.015, 0, -0.004
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0.005, 0, False, 0.005, 0, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False)
    Debug.Print "  C5结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    ' C6: FeatureExtrusion3 — 尝试作为Cut
    Debug.Print "--- C6: FeatureExtrusion3(29参) ---"
    swModel.InsertSketch2 True
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, False, 0, 0#, 0#, False, True, False, False, Nothing, Nothing)
    Debug.Print "  C6结果: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征数: " & featBefore & "→" & swModel.GetFeatureCount

    On Error GoTo ErrHandler

    ' ==================================================================
    ' 最终报告
    ' ==================================================================
    Debug.Print vbCrLf & "========== 最终报告 =========="
    Debug.Print "最终特征数: " & swModel.GetFeatureCount
    Dim swF As Object, i As Long
    For i = 1 To swModel.GetFeatureCount
        Set swF = swModel.FeatureByPositionReverse(i)
        If Not swF Is Nothing Then Debug.Print "  [" & i & "] " & swF.Name
    Next i

    swModel.ViewZoomtofit2
    MsgBox "v34 测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    On Error Resume Next: swModel.InsertSketch2 True
End Sub
