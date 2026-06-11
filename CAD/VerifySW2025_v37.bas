Option Explicit

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim bn As Long

Sub TestExtrusion2(count As Long, ByVal bb As Boolean)
    If bb Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.05, 0, -0.005, 0.05, 0, 0.005
        swSketchMgr.CreateLine 0.05, 0, 0.005, 0.05, 0.012, 0.005
        swSketchMgr.CreateLine 0.05, 0.012, 0.005, 0.05, 0.012, -0.005
        swSketchMgr.CreateLine 0.05, 0.012, -0.005, 0.05, 0, -0.005
        swModel.InsertSketch2 True
    End If
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    On Error Resume Next
    Select Case count
        Case 21
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False)
        Case 22
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False)
        Case 23
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False)
        Case 24
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False, False)
        Case 26
            Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False, False, False)
    End Select
    Debug.Print "  Extrusion2(" & count & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss-" & count
    On Error GoTo 0
End Sub

Sub TestFeatureCut3(count As Long)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.005, 0.01, -0.003, 0.02, 0.01, -0.003
    swSketchMgr.CreateLine 0.02, 0.01, -0.003, 0.02, 0.01, 0.003
    swSketchMgr.CreateLine 0.02, 0.01, 0.003, 0.005, 0.01, 0.003
    swSketchMgr.CreateLine 0.005, 0.01, 0.003, 0.005, 0.01, -0.003
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    On Error Resume Next
    Select Case count
        Case 24
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False, False, False)
        Case 25
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False, False, False, False)
        Case 26
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False, False, False, False, False)
        Case 27
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False, False, False, False, False, False)
        Case 28
            Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False, False, False, False, False, False, False)
    End Select
    Debug.Print "  Cut3(" & count & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut3-" & count
    On Error GoTo 0
End Sub

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

    ' === 0. 圆柱体 ===
    Debug.Print vbCrLf & "=== 0.圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"

    ' === 1. Extrusion2 参数扫描 (21→26) ===
    Debug.Print vbCrLf & "=== 1.Extrusion2 参数扫描 ==="
    TestExtrusion2 21, True
    TestExtrusion2 22, True
    TestExtrusion2 23, True
    TestExtrusion2 24, True
    TestExtrusion2 25, True
    TestExtrusion2 26, True

    ' === 2. FeatureExtrusion 参数扫描 (21→26) ===
    Debug.Print vbCrLf & "=== 2.FeatureExtrusion 参数扫描 ==="
    Dim k As Long
    For k = 21 To 26
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0.07, 0, -0.005, 0.07, 0, 0.005
        swSketchMgr.CreateLine 0.07, 0, 0.005, 0.07, 0.012, 0.005
        swSketchMgr.CreateLine 0.07, 0.012, 0.005, 0.07, 0.012, -0.005
        swSketchMgr.CreateLine 0.07, 0.012, -0.005, 0.07, 0, -0.005
        swModel.InsertSketch2 True
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        On Error Resume Next
        Select Case k
            Case 21
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False)
            Case 22
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False)
            Case 23
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False)
            Case 24
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False)
            Case 25
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False, False)
            Case 26
                Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, False, False, False)
        End Select
        Debug.Print "  Extrusion(" & k & ")=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Ext-" & k
        On Error GoTo ErrHandler
    Next k

    ' === 3. Cut3 参数扫描 (24→28) ===
    Debug.Print vbCrLf & "=== 3.Cut3 参数扫描 ==="
    TestFeatureCut3 24
    TestFeatureCut3 25
    TestFeatureCut3 26
    TestFeatureCut3 27
    TestFeatureCut3 28

    ' === 4. Cut5 测试 ===
    Debug.Print vbCrLf & "=== 4.Cut5(22参) ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.025, 0.01, -0.003, 0.04, 0.01, -0.003
    swSketchMgr.CreateLine 0.04, 0.01, -0.003, 0.04, 0.01, 0.003
    swSketchMgr.CreateLine 0.04, 0.01, 0.003, 0.025, 0.01, 0.003
    swSketchMgr.CreateLine 0.025, 0.01, 0.003, 0.025, 0.01, -0.003
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut5(True, False, False, False, 0#, 0, False, 0#, 0, False, False, 0#, 0#, False, False, 0#, 0#, False, False, False, False)
    Debug.Print "  Cut5(22)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount

    ' === 5. RevolveCut 修正几何 ===
    Debug.Print vbCrLf & "=== 5.RevolveCut 修正 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.008, 0, 0.04, 0.008, 0
    swSketchMgr.CreateLine 0.04, 0.008, 0, 0.04, 0.002, 0
    swSketchMgr.CreateLine 0.04, 0.002, 0, 0.02, 0.002, 0
    swSketchMgr.CreateLine 0.02, 0.002, 0, 0.02, 0.008, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "RevolveCut"

    ' === 6. RevolveCut 带中心线 ===
    Debug.Print vbCrLf & "=== 6.RevolveCut 带中心线 ==="
    swModel.InsertSketch2 True
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.02, 0.008, 0, 0.04, 0.008, 0
    swSketchMgr.CreateLine 0.04, 0.008, 0, 0.04, 0.002, 0
    swSketchMgr.CreateLine 0.04, 0.002, 0, 0.02, 0.002, 0
    swSketchMgr.CreateLine 0.02, 0.002, 0, 0.02, 0.008, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut3+CL=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount

    ' === 报告 ===
    On Error GoTo 0
    Debug.Print vbCrLf & "========== 报告 =========="
    Debug.Print "特征总数: " & swModel.GetFeatureCount
    Dim f As Object
    Dim j As Long
    For j = 1 To swModel.GetFeatureCount
        Set f = swModel.FeatureByPositionReverse(j)
        If Not f Is Nothing Then
            Debug.Print "  [" & j & "] " & f.Name
        End If
    Next
    swModel.ViewZoomtofit2
    MsgBox "v37 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
