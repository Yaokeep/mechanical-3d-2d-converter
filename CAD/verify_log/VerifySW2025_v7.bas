Option Explicit

' VerifySW2025 v7 - 修复 GetSelectionCount → GetSelectedObjectCount2(-1)
' v7: swModel.Extension.GetSelectionCount 不存在于 SW 2025 → 改用 SelectionManager.GetSelectedObjectCount2(-1)
' v6: CreateLine2→CreateLine, CreateCenterLine2→CreateCenterLine, FeatureRevolve2 3种方式

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim boolstatus As Boolean

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
    Debug.Print "Test1 [PASS] 零件: " & swModel.GetTitle

    ' ====== Test2: 创建草图 ======
    Debug.Print vbCrLf & "=== Test2: 创建草图 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0

    On Error Resume Next
    swModel.InsertSketch2 True
    Debug.Print "InsertSketch2: Err=" & Err.Number
    On Error GoTo ErrHandler

    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0

    ' 退出草图
    On Error Resume Next
    swModel.InsertSketch2 True
    If Err.Number <> 0 Then Err.Clear: swSketchMgr.InsertSketch
    On Error GoTo ErrHandler
    Debug.Print "Test2 [PASS] 草图OK"

    ' ====== Test3: FeatureRevolve2 ======
    Debug.Print vbCrLf & "=== Test3: FeatureRevolve2 ==="

    ' 关键: 退出草图后，选中它！
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Sketch1", "SKETCH", 0, 0, 0, False, 0, Nothing, 0
    Debug.Print "  选中 Sketch1: " & swModel.SelectionManager.GetSelectedObjectCount2(-1)

    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, False, False, False, False, False, _
        0, 0, 6.28318530717958, 0, _
        False, False, 0.01, 0.01, _
        0, 0, 0, True, True, True)
    Debug.Print "  方式A-选中草图后旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' 方式B: 如果不选中草图，重新打开草图再试
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True  ' 打开草图但不画东西
        swModel.InsertSketch2 True  ' 立即退出（激活已有草图）

        Set swFeat = swFeatMgr.FeatureRevolve2( _
            True, False, False, False, False, False, _
            0, 0, 6.28318530717958, 0, _
            False, False, 0.01, 0.01, _
            0, 0, 0, True, True, True)
        Debug.Print "  方式B-重新激活草图后旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式C: 在草图打开状态下旋转
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        ' 不退出草图，直接尝试
        Set swFeat = swFeatMgr.FeatureRevolve2( _
            True, False, False, False, False, False, _
            0, 0, 6.28318530717958, 0, _
            False, False, 0.01, 0.01, _
            0, 0, 0, True, True, True)
        Debug.Print "  方式C-草图打开时旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler

    If swFeat Is Nothing Then
        Debug.Print "Test3 [FAIL] 所有方式均失败"
        MsgBox "Test3 全部失败！后续测试跳过。", vbExclamation: Exit Sub
    End If
    swFeat.Name = "Test-Revolve"
    Debug.Print "Test3 [PASS]"

    ' ====== Test4-7 不变 ======
    Debug.Print vbCrLf & "=== Test4: InsertFeatureChamfer ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 50, 10, -0.001, 50, 10, 0.001, 0.0001, 2, True, 0, Nothing
    On Error Resume Next
    Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, 0#)
    Debug.Print "InsertFeatureChamfer(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Chamfer"
    Debug.Print "Test4 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    Debug.Print vbCrLf & "=== Test5: FeatureFillet3 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 0, 10, -0.001, 0, 10, 0.001, 0.0001, 2, True, 0, Nothing
    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
    Debug.Print "FeatureFillet3(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Fillet"
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    Debug.Print vbCrLf & "=== Test6: InsertRefPlane ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    On Error Resume Next
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="
    If swFeat Is Nothing Then
        Debug.Print "Test7 [SKIP]"
    Else
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        On Error Resume Next
        swModel.InsertSketch2 True
        If Err.Number <> 0 Then Err.Clear: swSketchMgr.InsertSketch
        On Error GoTo ErrHandler
        swSketchMgr.CreateLine 10, 10, -3, 30, 10, -3
        swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
        swSketchMgr.CreateLine 30, 10, 3, 10, 10, 3
        swSketchMgr.CreateLine 10, 10, 3, 10, 10, -3
        On Error Resume Next
        swModel.InsertSketch2 True
        If Err.Number <> 0 Then Err.Clear: swSketchMgr.InsertSketch
        On Error GoTo ErrHandler
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "FeatureCut3(26): " & IIf(swFeat Is Nothing, "Nothing", "OK")
        If Not swFeat Is Nothing Then swFeat.Name = "Test-Cut"
        Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation

    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    MsgBox "错误 #" & Err.Number & ": " & Err.Description, vbCritical
End Sub
