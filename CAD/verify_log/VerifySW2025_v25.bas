Option Explicit

' VerifySW2025 v25 - InsertRefPlane: 忽略返回值, 检查特征树是否有新平面
' 理论: SW2025 late-binding 下 InsertRefPlane 返回值有bug, 但平面可能已创建

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

    ' ====== 圆角 Options=195 (已验证OK) ======
    Debug.Print vbCrLf & "=== 圆角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0005, 0, 0, False, 0, False, False)
    Debug.Print "Fillet3(195): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    ' ====== 基准面 — 多种方式创建, 忽略返回值, 查特征树 ======
    Debug.Print vbCrLf & "=== 基准面 ==="
    Dim featBefore As Long, featAfter As Long
    Dim planeCreated As Boolean: planeCreated = False
    Dim testPlaneName As String: testPlaneName = ""
    On Error Resume Next

    ' 检查当前特征列表
    featBefore = swModel.GetFeatureCount
    Debug.Print "  初始特征数: " & featBefore

    ' V1: InsertRefPlane(8, 0.01, 0, 0, 0, 0) + 选中 Top Plane
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "V1-InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    featAfter = swModel.GetFeatureCount
    If featAfter > featBefore Then
        planeCreated = True
        Debug.Print "  → 特征数增加了! " & featBefore & "→" & featAfter
        ' 试选中新平面
        If Not swFeat Is Nothing Then
            swFeat.Name = "Test-Plane": testPlaneName = "Test-Plane"
        End If
    End If

    ' V2: InsertRefPlane(264, 0.01, 0, 0, 0, 0) — flip方向
    If Not planeCreated Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(264, 0.01, 0, 0, 0, 0)
        Debug.Print "V2-InsertRefPlane(264): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
        If featAfter > featBefore Then
            planeCreated = True
            If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane": testPlaneName = "Test-Plane"
        End If
    End If

    ' V3: InsertRefPlane(8, 0.01) — 2参
    If Not planeCreated Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01)
        Debug.Print "V3-InsertRefPlane(2): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
        If featAfter > featBefore Then
            planeCreated = True
            If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane": testPlaneName = "Test-Plane"
        End If
    End If

    ' V4: FeatureRefPlane (旧方法)
    If Not planeCreated Then
        featBefore = swModel.GetFeatureCount
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Err.Clear
        Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "V4-FeatureRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        featAfter = swModel.GetFeatureCount
        If featAfter > featBefore Then
            planeCreated = True
            If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane": testPlaneName = "Test-Plane"
        End If
    End If

    ' 如果以上都没创建平面，尝试通过名字找
    If Not planeCreated Then
        ' 试选 Plane1 (可能是之前V1/V2/V3/V4创建的, 只是返回值Nothing)
        Dim i As Long
        For i = 1 To 10
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Plane" & i, "PLANE", 0, 0, 0, False, 0, Nothing, 0
            If swSelMgr.GetSelectedObjectCount2(-1) > 0 Then
                Debug.Print "  → 找到 Plane" & i
                Set swFeat = swSelMgr.GetSelectedObject6(1, -1)
                If Not swFeat Is Nothing Then
                    swFeat.Name = "Test-Plane": testPlaneName = "Test-Plane"
                    planeCreated = True
                    Exit For
                End If
            End If
        Next i
    End If

    On Error GoTo ErrHandler
    Debug.Print "基准面: " & IIf(planeCreated, "[PASS]", "[FAIL]")

    ' ====== 切除 ======
    Debug.Print vbCrLf & "=== 切除 ==="
    If Not planeCreated Then
        Debug.Print "基准面未找到，跳过切除"
    Else
        On Error Resume Next
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 testPlaneName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
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

        ' FeatureCut(20) 回退
        If swFeat Is Nothing Then
            swModel.InsertSketch2 True
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 testPlaneName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 20, 0, -4, 30, 0, -4
            swSketchMgr.CreateLine 30, 0, -4, 30, 0, 4
            swSketchMgr.CreateLine 30, 0, 4, 20, 0, 4
            swSketchMgr.CreateLine 20, 0, 4, 20, 0, -4
            swModel.InsertSketch2 True
            Set swFeat = Nothing: Err.Clear
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                False, False, False, False, 0#, 0#, False, False, False, False, False, False)
            Debug.Print "T7 FeatureCut(20): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

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
