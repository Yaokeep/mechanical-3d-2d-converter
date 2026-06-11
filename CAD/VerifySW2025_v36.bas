Option Explicit

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim bn As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    On Error Resume Next

    ' ==========================================
    ' 0. 创建圆柱体基体 (FeatureRevolve2 已验证)
    ' ==========================================
    Debug.Print vbCrLf & "--- 0.圆柱体 ---"
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
    If swFeat Is Nothing Then
        MsgBox "圆柱体创建失败！", vbCritical
        Exit Sub
    End If
    swFeat.Name = "Cylinder"

    ' ==========================================
    ' 1. FeatureExtrusion2 - 凸台拉伸 (21参)
    ' 在Right Plane上画圆, 验证拉伸API是否可用
    ' ==========================================
    Debug.Print vbCrLf & "--- 1.Extrusion2凸台(21参) ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    swSketchMgr.CreateLine 0.025, 0, -0.005, 0.025, 0, 0.005
    swSketchMgr.CreateLine 0.025, 0, 0.005, 0.025, 0.01, 0.005
    swSketchMgr.CreateLine 0.025, 0.01, 0.005, 0.025, 0.01, -0.005
    swSketchMgr.CreateLine 0.025, 0.01, -0.005, 0.025, 0, -0.005
    swModel.InsertSketch2 True

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False)
    Debug.Print "  Extrusion2(21)凸台=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T1-Boss"

    ' ==========================================
    ' 2. FeatureExtrusion - 不带数字后缀
    ' SW2025 可能已重命名 (类似CreateLine2->CreateLine)
    ' ==========================================
    Debug.Print vbCrLf & "--- 2.Extrusion(21参) ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    swSketchMgr.CreateLine 0.04, 0.002, -0.005, 0.04, 0.002, 0.005
    swSketchMgr.CreateLine 0.04, 0.002, 0.005, 0.04, 0.008, 0.005
    swSketchMgr.CreateLine 0.04, 0.008, 0.005, 0.04, 0.008, -0.005
    swSketchMgr.CreateLine 0.04, 0.008, -0.005, 0.04, 0.002, -0.005
    swModel.InsertSketch2 True

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False)
    Debug.Print "  Extrusion(21)凸台=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T2-BossNoNum"

    ' ==========================================
    ' 3. FeatureRevolve2 IsCut=True - 旋转切除
    ' 验证IsCut参数是否生效
    ' ==========================================
    Debug.Print vbCrLf & "--- 3.Revolve2 IsCut=True ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    swSketchMgr.CreateLine 0.03, 0.005, 0, 0.04, 0.005, 0
    swSketchMgr.CreateLine 0.04, 0.005, 0, 0.04, 0, 0
    swSketchMgr.CreateLine 0.04, 0, 0, 0.03, 0, 0
    swSketchMgr.CreateLine 0.03, 0, 0, 0.03, 0.005, 0

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T3-RevolveCut"
    swModel.InsertSketch2 True

    ' ==========================================
    ' 4. FeatureCut3 - 草图打开状态, 13参数
    ' ==========================================
    Debug.Print vbCrLf & "--- 4.Cut3(13参)草图打开 ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    swSketchMgr.CreateLine 0.005, 0.01, -0.003, 0.02, 0.01, -0.003
    swSketchMgr.CreateLine 0.02, 0.01, -0.003, 0.02, 0.01, 0.003
    swSketchMgr.CreateLine 0.02, 0.01, 0.003, 0.005, 0.01, 0.003
    swSketchMgr.CreateLine 0.005, 0.01, 0.003, 0.005, 0.01, -0.003

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#)
    Debug.Print "  Cut3(13)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T4-Cut3-13"

    ' ==========================================
    ' 5. FeatureCut3 - 草图打开状态, 16参数
    ' ==========================================
    Debug.Print vbCrLf & "--- 5.Cut3(16参)草图打开 ---"
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    swSketchMgr.CreateLine 0.025, 0.01, -0.003, 0.04, 0.01, -0.003
    swSketchMgr.CreateLine 0.04, 0.01, -0.003, 0.04, 0.01, 0.003
    swSketchMgr.CreateLine 0.04, 0.01, 0.003, 0.025, 0.01, 0.003
    swSketchMgr.CreateLine 0.025, 0.01, 0.003, 0.025, 0.01, -0.003

    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False)

    Dim r5 As String
    r5 = IIf(swFeat Is Nothing, "FAIL", "PASS")
    Debug.Print "  Cut3(16)=" & r5 & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T5-Cut3-16"

    ' ==========================================
    ' 6. FeatureCut3 - 退出草图后, 22参数
    ' ==========================================
    Debug.Print vbCrLf & "--- 6.Cut3(22参)退出草图 ---"
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, False, False)

    Dim r6 As String
    r6 = IIf(swFeat Is Nothing, "FAIL", "PASS")
    Debug.Print "  Cut3(22)=" & r6 & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "T6-Cut3-22"

    ' ==========================================
    ' 报告
    ' ==========================================
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
    MsgBox "v36 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! 捕获错误 #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
