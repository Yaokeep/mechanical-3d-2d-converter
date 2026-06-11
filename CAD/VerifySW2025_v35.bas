Option Explicit

Dim swApp As Object, swModel As Object, swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, n As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW: " & swApp.RevisionNumber

    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' === 圆柱体 ===
    Debug.Print vbCrLf & "=== 圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0

    Set swFeat = Nothing
    Err.Clear
    n = swModel.GetFeatureCount
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, _
        0, 0, 0, True, True, True)
    Debug.Print "Revolve2(20): " & IIf(swFeat Is Nothing, "FAIL Err=" & Err.Number, "PASS 特征→" & swModel.GetFeatureCount)
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"

    ' === T1: FeatureExtrusion2 21参 正确签名 ===
    Debug.Print vbCrLf & "=== T1: FeatureExtrusion2(21参) ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.015, 0.01, -0.004, 0.035, 0.01, -0.004
    swSketchMgr.CreateLine 0.035, 0.01, -0.004, 0.035, 0.01, 0.004
    swSketchMgr.CreateLine 0.035, 0.01, 0.004, 0.015, 0.01, 0.004
    swSketchMgr.CreateLine 0.015, 0.01, 0.004, 0.015, 0.01, -0.004
    swModel.InsertSketch2 True

    n = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2( _
        True, False, False, _
        0, 0, _
        0.006, 0.006, _
        False, False, _
        False, False, _
        0#, 0#, _
        False, False, _
        0#, 0#, _
        False, _
        True, _
        False, False)
    Debug.Print "Extrusion2(21): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T1-Extrusion2"

    ' === T2: FeatureExtrusion 不带数字 (SW2025可能已重命名) ===
    Debug.Print vbCrLf & "=== T2: FeatureExtrusion(21参) ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.04, 0.01, -0.003, 0.055, 0.01, -0.003
    swSketchMgr.CreateLine 0.055, 0.01, -0.003, 0.055, 0.01, 0.003
    swSketchMgr.CreateLine 0.055, 0.01, 0.003, 0.04, 0.01, 0.003
    swSketchMgr.CreateLine 0.04, 0.01, 0.003, 0.04, 0.01, -0.003
    swModel.InsertSketch2 True

    n = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion( _
        True, False, False, _
        0, 0, _
        0.006, 0.006, _
        False, False, _
        False, False, _
        0#, 0#, _
        False, False, _
        0#, 0#, _
        False, _
        True, _
        False, False)
    Debug.Print "Extrusion(21): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T2-Extrusion"

    ' === T3: Revolve2 IsCut=True ===
    Debug.Print vbCrLf & "=== T3: Revolve2 IsCut=True ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.007, 0, 0.03, 0.007, 0
    swSketchMgr.CreateLine 0.03, 0.007, 0, 0.03, 0, 0
    swSketchMgr.CreateLine 0.03, 0, 0, 0.02, 0, 0
    swSketchMgr.CreateLine 0.02, 0, 0, 0.02, 0.007, 0

    n = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, True, False, True, False, False, _
        0, 0, _
        6.28318530717958, 0#, _
        False, False, _
        0.01, 0.01, _
        0, 0#, 0#, _
        True, True, True)
    Debug.Print "RevolveCut(20): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T3-RevolveCut"
    swModel.InsertSketch2 True

    ' === T4: FeatureCut3 草图打开 + 最少参数 ===
    Debug.Print vbCrLf & "=== T4: FeatureCut3(13参+草图打开) ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.06, 0.01, -0.003, 0.075, 0.01, -0.003
    swSketchMgr.CreateLine 0.075, 0.01, -0.003, 0.075, 0.01, 0.003
    swSketchMgr.CreateLine 0.075, 0.01, 0.003, 0.06, 0.01, 0.003
    swSketchMgr.CreateLine 0.06, 0.01, 0.003, 0.06, 0.01, -0.003

    n = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3( _
        True, False, False, _
        False, 0, 0.006, _
        False, 0, 0.006, _
        False, False, 0#, 0#)
    Debug.Print "Cut3(13): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T4-Cut3"

    ' === T5: FeatureCut3 16参+草图打开 ===
    Debug.Print vbCrLf & "=== T5: FeatureCut3(16参+草图打开) ==="
    If swFeat Is Nothing Then
        swModel.InsertSketch2 True
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.06, 0.01, -0.003, 0.075, 0.01, -0.003
        swSketchMgr.CreateLine 0.075, 0.01, -0.003, 0.075, 0.01, 0.003
        swSketchMgr.CreateLine 0.075, 0.01, 0.003, 0.06, 0.01, 0.003
        swSketchMgr.CreateLine 0.06, 0.01, 0.003, 0.06, 0.01, -0.003

        n = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3( _
            True, False, False, _
            False, 0, 0.006, _
            False, 0, 0.006, _
            False, False, 0#, 0#, _
            False, False, _
            False, False)
        Debug.Print "Cut3(16): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "T5-Cut3"
    Else
        Debug.Print "T5: 跳过 (T4已成功)"
    End If

    ' === T6: 选择圆柱面直接做草图 ===
    Debug.Print vbCrLf & "=== T6: 圆柱面草图+Extrusion2 ==="
    swModel.ClearSelection2 True
    Err.Clear
    swModel.Extension.SelectByID2 "", "FACE", 0.025, 0.01, 0, False, 0, Nothing, 0
    Debug.Print "选面: Err=" & Err.Number
    If Err.Number = 0 Then
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.015, 0.01, -0.004, 0.035, 0.01, -0.004
        swSketchMgr.CreateLine 0.035, 0.01, -0.004, 0.035, 0.01, 0.004
        swSketchMgr.CreateLine 0.035, 0.01, 0.004, 0.015, 0.01, 0.004
        swSketchMgr.CreateLine 0.015, 0.01, 0.004, 0.015, 0.01, -0.004
        swModel.InsertSketch2 True

        n = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureExtrusion2( _
            True, False, False, _
            0, 0, _
            0.006, 0.006, _
            False, False, _
            False, False, _
            0#, 0#, _
            False, False, _
            0#, 0#, _
            False, _
            True, _
            False, False)
        Debug.Print "Extrusion2(面): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number & " 特征:" & n & "→" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "T6-FaceExt"
    Else
        Debug.Print "T6: 跳过"
    End If

    ' === 报告 ===
    On Error GoTo 0
    Debug.Print vbCrLf & "========== 报告 =========="
    Debug.Print "特征总数: " & swModel.GetFeatureCount
    Dim f As Object, i As Long
    For i = 1 To swModel.GetFeatureCount
        Set f = swModel.FeatureByPositionReverse(i)
        If Not f Is Nothing Then Debug.Print "  [" & i & "] " & f.Name
    Next
    swModel.ViewZoomtofit2
    MsgBox "v35 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
