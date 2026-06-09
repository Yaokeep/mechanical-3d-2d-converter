Option Explicit

' VerifySW2025 v23 - 用 IModelDoc2.CreatePlaneAtOffset3 创建基准面
' 发现: InsertRefPlane 在 FeatureManager 上不工作
' CreatePlaneAtOffset3(Val, FlipDir, AutoSize) 在 swModel 上

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

    ' ====== 旋转体 ======
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
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")

    ' ====== 倒角 (已验证OK) ======
    Debug.Print vbCrLf & "=== 倒角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    ' ====== 圆角 — 选面后圆角 ======
    Debug.Print vbCrLf & "=== 圆角 ==="
    On Error Resume Next

    ' 选择圆柱面 → 圆角
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
    Debug.Print "  选面: " & swSelMgr.GetSelectedObjectCount2(-1)

    ' Fillet3(8参) - 选面后圆角面内所有边
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, False, 0, False, False)
    Debug.Print "T5-Fillet3(面): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' Fillet3 不同参数组合
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0005, 0, 0, False, 0, False, False)
        Debug.Print "T5-Fillet3(195): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' FeatureFillet 旧版
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-Fillet(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== 基准面 — CreatePlaneAtOffset3(swModel方法) ======
    Debug.Print vbCrLf & "=== 基准面 ==="
    On Error Resume Next

    ' T6-1: swModel.CreatePlaneAtOffset3(offset_m, FlipDir, AutoSize)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swModel.CreatePlaneAtOffset3(0.01, False, True)
    Debug.Print "T6-1 CreatePlaneAtOffset3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T6-2: CreatePlaneAtOffset (旧版2参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swModel.CreatePlaneAtOffset(0.01, False)
        Debug.Print "T6-2 CreatePlaneAtOffset: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-3: CreatePlaneAtOffset3(offset, True, True)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swModel.CreatePlaneAtOffset3(0.01, True, True)
        Debug.Print "T6-3 Offset(flip=True): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-4: Front Plane 偏移
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swModel.CreatePlaneAtOffset3(0.01, False, True)
        Debug.Print "T6-4 Front Offset: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-5: CreatePlaneThru3Points3
    If swFeat Is Nothing Then
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swModel.CreatePlaneThru3Points3(True, 0, 10, 0, 50, 10, 0, 0, 5, 10)
        Debug.Print "T6-5 Thru3Points: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    Debug.Print "基准面: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== 切除 ======
    Debug.Print vbCrLf & "=== 切除 ==="
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
        Debug.Print "T7 Cut3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        On Error GoTo ErrHandler
    End If
    Debug.Print "切除: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    On Error Resume Next: swModel.InsertSketch2 True
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
