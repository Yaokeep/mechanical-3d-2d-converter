Option Explicit

' VerifySW2025 v29 - 绕过基准面, 从 Front Plane 直接 FeatureCut3 测试
' SW2025 Bug: GetSelectedObjectCount2(-1)始终返回0 → InsertRefPlane内部检查失败
' 解决: 草图在默认基准面上, 不创建新基准面

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

    ' ====== 倒角 (已验证) ======
    Debug.Print vbCrLf & "=== 倒角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    ' ====== 圆角 (已验证 Options=195) ======
    Debug.Print vbCrLf & "=== 圆角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0005, 0, 0, False, 0, False, False)
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    ' ====== FeatureCut3: Front Plane 直接切除 (Z方向贯穿) ======
    Debug.Print vbCrLf & "=== FeatureCut3: Front Plane → Z方向贯穿 ==="
    On Error Resume Next

    ' 在Front Plane(XY平面)上画矩形, 切除方向Z
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 矩形: X=20-30, Y=4-8 (在圆柱体内部, 圆柱半径10mm)
    swSketchMgr.CreateLine 20, 4, 0, 30, 4, 0
    swSketchMgr.CreateLine 30, 4, 0, 30, 8, 0
    swSketchMgr.CreateLine 30, 8, 0, 20, 8, 0
    swSketchMgr.CreateLine 20, 8, 0, 20, 4, 0
    Debug.Print "  矩形: X=20-30, Y=4-8 (草图打开)"

    ' C1: FeatureCut3(26) 贯穿
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
    Debug.Print "C1-Cut3(26,草图打开): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' C2: FeatureCut3 退出草图后
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
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
        Debug.Print "C2-Cut3(26,退出后): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' C3: FeatureCut(20) 退出后 + 新草图
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 4, 0, 30, 4, 0
        swSketchMgr.CreateLine 30, 4, 0, 30, 8, 0
        swSketchMgr.CreateLine 30, 8, 0, 20, 8, 0
        swSketchMgr.CreateLine 20, 8, 0, 20, 4, 0
        swModel.InsertSketch2 True
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, False)
        Debug.Print "C3-FeatureCut(20): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' C4: TopPlane 直接切除 (Y方向)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        ' Top Plane = XZ, 矩形X=20-30, Z=-4-4
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
        Debug.Print "C4-TopPlane Cut3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' C5: FeatureCut4
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 0, -4, 30, 0, -4
        swSketchMgr.CreateLine 30, 0, -4, 30, 0, 4
        swSketchMgr.CreateLine 30, 0, 4, 20, 0, 4
        swSketchMgr.CreateLine 20, 0, 4, 20, 0, -4
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.FeatureCut4(True, False, False, _
            False, 0, 0.005, _
            False, 0, 0.005, _
            False, False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, 0#, _
            False, False)
        Debug.Print "C5-Cut4(28): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "切除: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    On Error Resume Next: swModel.InsertSketch2 True
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
