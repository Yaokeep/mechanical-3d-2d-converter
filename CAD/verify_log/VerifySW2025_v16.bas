Option Explicit

' VerifySW2025 v16 - Test7: 草图不退出直接FeatureCut3
' v15: Test5+6 PASS, Test7 FAIL (退出草图后才切除)

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object, featOk As Boolean

Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swPart = swApp.ActiveDoc
    If swPart Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    Set swModel = swPart
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ====== 创建旋转体 ======
    Debug.Print "=== 创建旋转体 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")

    ' ====== Test5: Fillet ======
    Debug.Print vbCrLf & "=== Test5: Fillet ==="
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    Debug.Print "Fillet: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If swFeat Is Nothing Then MsgBox "Fillet失败", vbCritical: Exit Sub
    swFeat.Name = "Test-Fillet"
    Debug.Print "Test5 [PASS]"

    ' ====== Test6: RefPlane ======
    Debug.Print vbCrLf & "=== Test6: RefPlane ==="
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "RefPlane: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If swFeat Is Nothing Then MsgBox "RefPlane失败", vbCritical: Exit Sub
    swFeat.Name = "Test-Plane"
    Debug.Print "Test6 [PASS]"

    ' ====== Test7: FeatureCut3 — 草图打开时直接切除 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="

    ' 在基准面上插入草图 (不退出)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 画矩形 (基准面偏移10mm, 矩形在局部坐标 X=20~30, Z=-3~3)
    swSketchMgr.CreateLine 20, 0, -3, 30, 0, -3
    swSketchMgr.CreateLine 30, 0, -3, 30, 0, 3
    swSketchMgr.CreateLine 30, 0, 3, 20, 0, 3
    swSketchMgr.CreateLine 20, 0, 3, 20, 0, -3
    Debug.Print "  矩形已绘制 (草图打开中)"

    ' 方式A: FeatureCut3(26参) — 草图打开状态
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
        False, False, False, False, 0#, 0#, False, False, False, False, False, _
        True, True, False, False, False, 0, 0#, False)
    Debug.Print "A-FeatureCut3(26,草图打开): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' 方式B: 退出草图后 FeatureCut3
    If swFeat Is Nothing Then
        Err.Clear
        swModel.InsertSketch2 True  ' 退出
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "B-FeatureCut3(26,退出后): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式C: FeatureCut4 (如果存在)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 0, -3, 30, 0, -3
        swSketchMgr.CreateLine 30, 0, -3, 30, 0, 3
        swSketchMgr.CreateLine 30, 0, 3, 20, 0, 3
        swSketchMgr.CreateLine 20, 0, 3, 20, 0, -3
        Set swFeat = swFeatMgr.FeatureCut4(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False, False)
        Debug.Print "C-FeatureCut4(28): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式D: 在 Front Plane 上画草图切除 (X方向切深)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        ' 在圆柱体中部画一个小圆 (Y=-3~3, Z=0, X=25)
        swSketchMgr.CreateLine 25, -3, 0, 25, 3, 0
        swSketchMgr.CreateLine 25, 3, 0, 35, 3, 0
        swSketchMgr.CreateLine 35, 3, 0, 35, -3, 0
        swSketchMgr.CreateLine 35, -3, 0, 25, -3, 0
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "D-FrontPlane-FeatureCut3(26): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式E: FeatureCut5
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 25, -3, 0, 25, 3, 0
        swSketchMgr.CreateLine 25, 3, 0, 35, 3, 0
        swSketchMgr.CreateLine 35, 3, 0, 35, -3, 0
        swSketchMgr.CreateLine 35, -3, 0, 25, -3, 0
        Set swFeat = swFeatMgr.FeatureCut5(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False, False, False)
        Debug.Print "E-FeatureCut5(30): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then
        swFeat.Name = "Test-Cut"
    End If
    Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
