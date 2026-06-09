Option Explicit

' VerifySW2025 v33 - 精简版: 聚焦基准面+切除
' 移除导致语法错误的过多续行, 只保留关键测试

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object
Dim boolstatus As Boolean, featBefore As Long, featAfter As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    featBefore = swModel.GetFeatureCount
    Debug.Print "初始特征数: " & featBefore

    ' ==================================================================
    ' 测试1: 旋转体 (已知可行的方法)
    ' ==================================================================
    Debug.Print vbCrLf & "=== 测试1: 旋转体 ==="
    On Error Resume Next

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 简单圆柱: 半径10mm, 长50mm, 绕X轴
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0

    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL Err=" & Err.Number, "PASS (" & swFeat.Name & ")")
    Debug.Print "  特征: " & featBefore & "→" & swModel.GetFeatureCount

    On Error GoTo ErrHandler

    ' 如果旋转体失败就退出
    If swFeat Is Nothing Then
        MsgBox "旋转体创建失败!", vbCritical: Exit Sub
    End If

    ' ==================================================================
    ' 测试2: 基准面创建 (关键!)
    ' 使用官方文档确切模式: 不用括号 + Append=True + 整数0
    ' ==================================================================
    Debug.Print vbCrLf & "=== 测试2: 基准面创建 ==="
    On Error Resume Next

    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Debug.Print "选Front(Append=True): Err=" & Err.Number

    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "InsertRefPlane: " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
    Debug.Print "  特征: " & featBefore & "→" & swModel.GetFeatureCount

    ' 也试试中文名
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
        Debug.Print "选前视(中文): Err=" & Err.Number
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "InsertRefPlane(中文): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
        Debug.Print "  特征: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' Top Plane 偏移
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
        Debug.Print "选Top: Err=" & Err.Number
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.02, 0, 0, 0, 0)
        Debug.Print "InsertRefPlane(Top): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number
        Debug.Print "  特征: " & featBefore & "→" & swModel.GetFeatureCount
    End If

    On Error GoTo ErrHandler

    ' ==================================================================
    ' 测试3: FeatureCut — 逐个尝试, 失败的跳过
    ' 使用非常简洁的调用, 避免续行符问题
    ' ==================================================================
    Debug.Print vbCrLf & "=== 测试3: FeatureCut ==="
    On Error Resume Next

    ' 先画一个简单草图在 Top Plane
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 矩形 20x6mm, X=20-40, Z=-3~3
    swSketchMgr.CreateLine 0.02, 0, -0.003, 0.04, 0, -0.003
    swSketchMgr.CreateLine 0.04, 0, -0.003, 0.04, 0, 0.003
    swSketchMgr.CreateLine 0.04, 0, 0.003, 0.02, 0, 0.003
    swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
    Debug.Print "草图: 矩形20x6, TopPlane"

    ' C1: FeatureCut3 — ThroughAll, 26参数 (和v29一样)
    featBefore = swModel.GetFeatureCount
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.005, False, 0, 0.005, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False, Nothing, False)
    Debug.Print "C1-Cut3(26): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number & " feat:" & featBefore & "→" & swModel.GetFeatureCount

    ' C2: FeatureCut3 — ThroughAll, 26参数, EndType用整数0
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.04, 0, -0.003
        swSketchMgr.CreateLine 0.04, 0, -0.003, 0.04, 0, 0.003
        swSketchMgr.CreateLine 0.04, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0, False, 0, 0, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False, Nothing, False)
        Debug.Print "C2-Cut3(EndType=0): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number & " feat:" & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C3: FeatureCut3 — 盲孔, 深度5mm
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.04, 0, -0.003
        swSketchMgr.CreateLine 0.04, 0, -0.003, 0.04, 0, 0.003
        swSketchMgr.CreateLine 0.04, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3(False, False, False, False, 0.005, 0, False, 0.005, 0, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False, Nothing, False)
        Debug.Print "C3-Cut3(Blind5mm): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number & " feat:" & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C4: FeatureCut(简单版本) — 9参数
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.04, 0, -0.003
        swSketchMgr.CreateLine 0.04, 0, -0.003, 0.04, 0, 0.003
        swSketchMgr.CreateLine 0.04, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
        swModel.InsertSketch2 True  ' 退出草图
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, False, False, False, False)
        Debug.Print "C4-Cut(19参,退出草图): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number & " feat:" & featBefore & "→" & swModel.GetFeatureCount
    End If

    ' C5: FeatureCut4 — 28参数
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.02, 0, -0.003, 0.04, 0, -0.003
        swSketchMgr.CreateLine 0.04, 0, -0.003, 0.04, 0, 0.003
        swSketchMgr.CreateLine 0.04, 0, 0.003, 0.02, 0, 0.003
        swSketchMgr.CreateLine 0.02, 0, 0.003, 0.02, 0, -0.003
        featBefore = swModel.GetFeatureCount
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut4(True, False, False, False, 0.005, 0, False, 0.005, 0, False, False, 0#, False, 0#, False, 0#, False, 0#, False, 0#, False, False)
        Debug.Print "C5-Cut4(23参): " & IIf(swFeat Is Nothing, "Nothing", swFeat.Name) & " Err=" & Err.Number & " feat:" & featBefore & "→" & swModel.GetFeatureCount
    End If

    On Error GoTo ErrHandler

    ' 最终报告
    Debug.Print vbCrLf & "最终特征数: " & swModel.GetFeatureCount
    Dim swF As Object, i As Long
    For i = 1 To swModel.GetFeatureCount
        Set swF = swModel.FeatureByPositionReverse(i)
        If Not swF Is Nothing Then Debug.Print "  [" & i & "] " & swF.Name
    Next i

    swModel.ViewZoomtofit2
    MsgBox "v33 测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    On Error Resume Next: swModel.InsertSketch2 True
End Sub
