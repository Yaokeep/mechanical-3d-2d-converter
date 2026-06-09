Option Explicit

' VerifySW2025 v12 - Test5(Fillet)+Test6(RefPlane)+Test7(Cut) 一次性验证
' 已知: SelectByRay 不可用, 选边用 SelectByID2("", "EDGE", X, Y, Z, ...)

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object

Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber

    Set swPart = swApp.ActiveDoc
    If swPart Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    End If
    Set swModel = swPart
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager
    Debug.Print "Test1 [PASS] 零件: " & swModel.GetTitle

    ' ====== 创建实体旋转体 ======
    Debug.Print vbCrLf & "=== 创建实体旋转体 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, _
        False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " | " & swFeat.Name
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    ' ====== Test5: FeatureFillet3 — 圆角 ======
    Debug.Print vbCrLf & "=== Test5: FeatureFillet3 ==="

    swModel.ClearSelection2 True
    On Error Resume Next

    ' 方式A: 选圆柱体端面圆边 (X=50, Y=10, Z=0 处)
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Debug.Print "T5-选边: Err=" & Err.Number & " n=" & swSelMgr.GetSelectedObjectCount2(-1)

    ' 尝试 FeatureFillet3: (Options, Radius, EdgeCount, ..., ...)
    Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
    Debug.Print "T5-方式A(8参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' 方式B: 选中面的边, 不同参数
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, False, 0, True, True)
        Debug.Print "T5-方式B(PROPA=False): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式C: 选 X=0 处的边
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
        Debug.Print "T5-方式C(X=0): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式D: FeatureFillet (旧版, 7参数)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 1, 0, 0, 0, 0, 0)
        Debug.Print "T5-方式D-FeatureFillet(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: InsertRefPlane — 偏移基准面 ======
    Debug.Print vbCrLf & "=== Test6: InsertRefPlane ==="
    swModel.ClearSelection2 True

    On Error Resume Next
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "T6-InsertRefPlane(6参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then Debug.Print "  基准面: " & swFeat.Name

    ' 回退: InsertRefPlane(4参)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0)
        Debug.Print "T6-InsertRefPlane(4参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Dim planeFeatName As String
    If Not swFeat Is Nothing Then
        planeFeatName = "Test-Plane"
        swFeat.Name = planeFeatName
    End If
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: FeatureCut3 — 拉伸切除 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="
    If swFeat Is Nothing Then
        Debug.Print "Test7 [SKIP] (基准面创建失败)"
    Else
        ' 在新基准面上画矩形并切除
        On Error Resume Next
        swModel.Extension.SelectByID2 planeFeatName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear
        swModel.InsertSketch2 True
        Debug.Print "T7-开草图: Err=" & Err.Number

        ' 画矩形 (在基准面上, X=20~30, Z=-3~3)
        swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
        swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
        swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
        swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3

        ' 退出草图
        Err.Clear
        swModel.InsertSketch2 True
        Debug.Print "T7-退草图: Err=" & Err.Number

        ' FeatureCut3: 向下切除 3mm = 0.003m
        Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "T7-FeatureCut3(26参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  切除: " & swFeat.Name

        ' 方式B: FeatureCut (18参数)
        If swFeat Is Nothing And Err.Number <> 0 Then
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 planeFeatName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
            swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
            swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
            swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3
            swModel.InsertSketch2 True
            Err.Clear
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, 0, 0, 0.003, 0.003, _
                False, False, False, False, 0#, 0#, False, False, False, False)
            Debug.Print "T7-FeatureCut(18参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        On Error GoTo ErrHandler
        If Not swFeat Is Nothing Then
            swFeat.Name = "Test-Cut"
        End If
        Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
