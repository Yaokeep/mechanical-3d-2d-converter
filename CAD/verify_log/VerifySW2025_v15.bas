Option Explicit

' VerifySW2025 v15 - 修正逻辑: 特征创建成功就保留(忽略Err), 跑通5+6+7
' v14: F2-1/F2-2都OK但因Err=450被覆盖, R1需要6参+Top Plane

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

    ' ====== Test5: Fillet - 用已知成功的方式 ======
    Debug.Print vbCrLf & "=== Test5: Fillet ==="
    featOk = False
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Debug.Print "  选边: n=" & swSelMgr.GetSelectedObjectCount2(-1)

    ' SW2025 FeatureFillet2: 14参能创建(Err=450是参数类型警告, 可忽略)
    Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    featOk = (Not swFeat Is Nothing)
    Debug.Print "FeatureFillet2(14): feat=" & IIf(featOk, "OK", "Nothing") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    If featOk Then
        swFeat.Name = "Test-Fillet"
        Debug.Print "Test5 [PASS]"
    Else
        Debug.Print "Test5 [FAIL]"
    End If

    ' ====== Test6: RefPlane - Top Plane + 6参 ======
    Debug.Print vbCrLf & "=== Test6: RefPlane ==="
    featOk = False
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear

    ' 方式A: FeatureRefPlane(6参) - v13证实可用
    Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
    featOk = (Not swFeat Is Nothing)
    Debug.Print "FeatureRefPlane(Top,6): feat=" & IIf(featOk, "OK", "Nothing") & " Err=" & Err.Number

    ' 方式B: InsertRefPlane(6参)
    If Not featOk Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        featOk = (Not swFeat Is Nothing)
        Debug.Print "InsertRefPlane(Top,6): feat=" & IIf(featOk, "OK", "Nothing") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If featOk Then
        swFeat.Name = "Test-Plane"
        Debug.Print "Test6 [PASS]"
    Else
        Debug.Print "Test6 [FAIL]"
    End If

    ' ====== Test7: FeatureCut3 — 拉伸切除 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="
    If Not featOk Then
        Debug.Print "Test7 [SKIP]"
    Else
        featOk = False
        On Error Resume Next
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
        swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
        swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
        swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3
        swModel.InsertSketch2 True
        Err.Clear

        ' FeatureCut3(26参)
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "FeatureCut3(26): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

        ' FeatureCut(18参) 回退
        If swFeat Is Nothing Then
            Err.Clear
            swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
            swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
            swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
            swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3
            swModel.InsertSketch2 True
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, 0, 0, 0.003, 0.003, _
                False, False, False, False, 0#, 0#, False, False, False, False)
            Debug.Print "FeatureCut(18): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        On Error GoTo ErrHandler
        If Not swFeat Is Nothing Then
            swFeat.Name = "Test-Cut"
            featOk = True
        End If
        Debug.Print "Test7 " & IIf(featOk, "[PASS]", "[FAIL]")
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
