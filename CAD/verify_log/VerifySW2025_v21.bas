Option Explicit

' VerifySW2025 v21 - 修正假阳性: 每次调用前 Set swFeat = Nothing
' v20: 发现 swFeat 保留旧值导致所有测试虚假 PASS

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ====== 创建旋转体 ======
    Debug.Print "=== 旋转体 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = Nothing
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL(真)", "PASS(真)") & " | Err=" & Err.Number
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    ' ====== Test4: 倒角 ======
    Debug.Print vbCrLf & "=== Test4: 倒角 ==="
    On Error Resume Next

    ' 选边 X=50, Y=10 (右端面)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Debug.Print "T4-选边: " & swSelMgr.GetSelectedObjectCount2(-1)

    ' T4-1: InsertFeatureChamfer, Type=1(角度-距离), 45deg, 1mm
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "T4-1 Type=1: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T4-2: InsertFeatureChamfer, Type=2(距离-距离), 1mm
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, 0#, False)
        Debug.Print "T4-2 Type=2: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T4-3: 选面倒角
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "FACE", 50, 5, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "T4-3 选面: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T4-4: 选左端面边
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "T4-4 左端边: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test5: 圆角 ======
    Debug.Print vbCrLf & "=== Test5: 圆角 ==="
    On Error Resume Next

    ' T5-1: FeatureFillet3 (8参, Err=0)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Debug.Print "T5-选边: " & swSelMgr.GetSelectedObjectCount2(-1)
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
    Debug.Print "T5-1 Fillet3(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T5-2: FeatureFillet3 (10参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True, False, False)
        Debug.Print "T5-2 Fillet3(10): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-3: FeatureFillet (7参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 1, 0, 0, 0, 0, 0)
        Debug.Print "T5-3 Fillet(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-4: FeatureFillet (10参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 1, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-4 Fillet(10): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-5: InsertFeatureFillet?
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureFillet(1, 0.0005, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-5 InsertFillet(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: 基准面 ======
    Debug.Print vbCrLf & "=== Test6: 基准面 ==="
    On Error Resume Next

    ' T6-1: InsertRefPlane (8, offset, 0,0,0,0,0) = 7参
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0, 0)
    Debug.Print "T6-1 InsertRefPlane(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T6-2: InsertRefPlane (8, offset, 0,0,0,0) = 6参
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "T6-2 InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-3: InsertRefPlane (8, offset, False, False, False, False) = Boolean型
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, False, False, False, False)
        Debug.Print "T6-3 InsertRefPlane(Bool): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-4: InsertRefPlane(2, ...) 平行平面
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(2, 0, 0, 0, 0, 0)
        Debug.Print "T6-4 InsertRefPlane(2,平行): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    Debug.Print "基准面: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: 切除 ======
    Debug.Print vbCrLf & "=== Test7: 切除 ==="
    If swFeat Is Nothing Then
        Debug.Print "基准面失败，跳过切除"
    Else
        On Error Resume Next
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 0, -4, 30, 0, -4
        swSketchMgr.CreateLine 30, 0, -4, 30, 0, 4
        swSketchMgr.CreateLine 30, 0, 4, 20, 0, 4
        swSketchMgr.CreateLine 20, 0, 4, 20, 0, -4

        ' T7-1: FeatureCut3 草图打开
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3( _
            True, False, False, _
            False, 0, 0.005, _
            False, 0, 0.005, _
            False, False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, False, Nothing, False)
        Debug.Print "T7-1 Cut3(26): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

        ' T7-2: FeatureCut (18) 草图退出后
        If swFeat Is Nothing Then
            swModel.InsertSketch2 True
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 20, 0, -4, 30, 0, -4
            swSketchMgr.CreateLine 30, 0, -4, 30, 0, 4
            swSketchMgr.CreateLine 30, 0, 4, 20, 0, 4
            swSketchMgr.CreateLine 20, 0, 4, 20, 0, -4
            swModel.InsertSketch2 True
            Set swFeat = Nothing: Err.Clear
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                False, False, False, False, 0#, 0#, False, False, False, False, False, False)
            Debug.Print "T7-2 FeatureCut(20): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        ' T7-3: Front Plane 贯穿切除
        If swFeat Is Nothing Then
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 22, 4, 0, 28, 4, 0
            swSketchMgr.CreateLine 28, 4, 0, 28, 8, 0
            swSketchMgr.CreateLine 28, 8, 0, 22, 8, 0
            swSketchMgr.CreateLine 22, 8, 0, 22, 4, 0
            Set swFeat = Nothing: Err.Clear
            Set swFeat = swFeatMgr.FeatureCut3( _
                True, False, False, _
                False, 0, 0.005, _
                False, 0, 0.005, _
                False, False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, False, Nothing, False)
            Debug.Print "T7-3 FrontCut3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        On Error GoTo ErrHandler
    End If
    Debug.Print "切除: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    On Error Resume Next
    swModel.InsertSketch2 True
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
