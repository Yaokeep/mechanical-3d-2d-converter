Option Explicit

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object

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
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    Debug.Print vbCrLf & "=== Test7: FeatureCut 贯穿切除 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
    swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
    swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
    swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5
    Debug.Print "  矩形15~35 Z:-5~5 (TopPlane, 草图打开)"

    On Error Resume Next
    Err.Clear
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
    Debug.Print "Cut3(26参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
        swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
        swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
        swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5
        Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
            False, False, False, False, 0#, 0#, False, False, False, False)
        Debug.Print "FeatureCut(18参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 3, 0, 30, 3, 0
        swSketchMgr.CreateLine 30, 3, 0, 30, 8, 0
        swSketchMgr.CreateLine 30, 8, 0, 20, 8, 0
        swSketchMgr.CreateLine 20, 8, 0, 20, 3, 0
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
        Debug.Print "Cut3(FrontPlane): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Cut"
    Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")
    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
