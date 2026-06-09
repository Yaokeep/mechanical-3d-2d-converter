Option Explicit

' VerifySW2025 v8 - 不退出草图，直接调用 FeatureRevolve2
' v7: GetSelectionCount→GetSelectedObjectCount2 (修复 Error 438)
' v8: 草图不退出，在激活状态下直接旋转（标准 SW API 流程）

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
    Debug.Print "Test2 [PASS] 草图OK (5条线, 草图未退出)"

    ' ====== Test3: FeatureRevolve2 — 草图打开时直接旋转 ======
    Debug.Print vbCrLf & "=== Test3: FeatureRevolve2 ==="

    ' 方式A: 草图仍然打开，直接调用 FeatureRevolve2
    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, False, False, False, False, False, _
        0, 0, 6.28318530717958, 0, _
        False, False, 0.01, 0.01, _
        0, 0, 0, True, True, True)
    Debug.Print "  方式A-草图打开时旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name

    ' 方式B: 先退出草图再插入，然后旋转
    If swFeat Is Nothing Then
        Err.Clear
        ' 退出当前草图
        swModel.InsertSketch2 True
        Debug.Print "  退出草图: Err=" & Err.Number
        Err.Clear

        ' 重新开始: 选面→插入新草图→画线→旋转
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
        swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
        swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
        swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
        swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0

        Set swFeat = swFeatMgr.FeatureRevolve2( _
            True, False, False, False, False, False, _
            0, 0, 6.28318530717958, 0, _
            False, False, 0.01, 0.01, _
            0, 0, 0, True, True, True)
        Debug.Print "  方式B-新草图直接旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    ' 方式C: 用 InsertSketch 替代 InsertSketch2
    If swFeat Is Nothing Then
        Err.Clear
        swModel.InsertSketch2 True  ' 退出当前草图
        Err.Clear

        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swSketchMgr.InsertSketch  ' SW2025: ISketchManager.InsertSketch (无2后缀)
        swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
        swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
        swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
        swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
        swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0

        Set swFeat = swFeatMgr.FeatureRevolve2( _
            True, False, False, False, False, False, _
            0, 0, 6.28318530717958, 0, _
            False, False, 0.01, 0.01, _
            0, 0, 0, True, True, True)
        Debug.Print "  方式C-InsertSketch+旋转(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    ' 方式D: 尝试 18 参数版 FeatureRevolve2
    If swFeat Is Nothing Then
        Err.Clear
        swModel.InsertSketch2 True
        Err.Clear

        swModel.ClearSelection2 True
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
            False, False, 0, 0, _
            True, True, True, 0, 0)
        Debug.Print "  方式D-18参数版旋转: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    On Error GoTo ErrHandler

    If swFeat Is Nothing Then
        Debug.Print "Test3 [FAIL] 所有方式均失败"
        MsgBox "Test3 全部失败！后续测试跳过。", vbExclamation: Exit Sub
    End If
    swFeat.Name = "Test-Revolve"
    Debug.Print "Test3 [PASS]"

    ' ====== Test4: InsertFeatureChamfer ======
    Debug.Print vbCrLf & "=== Test4: InsertFeatureChamfer ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 50, 10, -0.001, 50, 10, 0.001, 0.0001, 2, True, 0, Nothing
    On Error Resume Next
    Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, 0#)
    Debug.Print "InsertFeatureChamfer(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Chamfer"
    Debug.Print "Test4 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test5: FeatureFillet3 ======
    Debug.Print vbCrLf & "=== Test5: FeatureFillet3 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 0, 10, -0.001, 0, 10, 0.001, 0.0001, 2, True, 0, Nothing
    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
    Debug.Print "FeatureFillet3(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Fillet"
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: InsertRefPlane ======
    Debug.Print vbCrLf & "=== Test6: InsertRefPlane ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    On Error Resume Next
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: FeatureCut3 ======
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
