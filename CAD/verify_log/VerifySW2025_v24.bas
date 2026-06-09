Option Explicit

' VerifySW2025 v24 - 圆角OK(Options=195)! 验证基准面是否真实创建
' CreatePlaneAtOffset3 可能已创建但返回值问题 → 查特征树

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

    ' ====== 圆角 — Options=195 (已验证OK) ======
    Debug.Print vbCrLf & "=== 圆角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 25, 0, 10, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.0005, 0, 0, False, 0, False, False)
    Debug.Print "Fillet3(195): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Fillet"
    On Error GoTo ErrHandler
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== 基准面 — 验证是否已创建 ======
    Debug.Print vbCrLf & "=== 基准面 ==="
    On Error Resume Next

    Dim featCountBefore As Long
    featCountBefore = swModel.GetFeatureCount
    Debug.Print "  创建前特征数: " & featCountBefore

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swModel.CreatePlaneAtOffset3(0.01, False, True)
    Debug.Print "CreatePlaneAtOffset3: ret=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    Dim featCountAfter As Long
    featCountAfter = swModel.GetFeatureCount
    Debug.Print "  创建后特征数: " & featCountAfter

    ' 尝试选中新基准面 (Y=10mm)
    Dim foundPlane As Boolean: foundPlane = False
    If featCountAfter > featCountBefore Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "PLANE", 0, 0.01, 0, False, 0, Nothing, 0
        foundPlane = (swSelMgr.GetSelectedObjectCount2(-1) > 0)
        Debug.Print "  选Y=0.01: " & IIf(foundPlane, "找到", "没找到")

        If Not foundPlane Then
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "", "PLANE", 0, -0.01, 0, False, 0, Nothing, 0
            foundPlane = (swSelMgr.GetSelectedObjectCount2(-1) > 0)
            Debug.Print "  选Y=-0.01: " & IIf(foundPlane, "找到", "没找到")
        End If

        ' 如果找到平面，重命名
        If foundPlane And swFeat Is Nothing Then
            Set swFeat = swSelMgr.GetSelectedObject6(1, -1)
            If Not swFeat Is Nothing Then
                swFeat.Name = "Test-Plane"
                Debug.Print "  基准面已重命名为 Test-Plane"
            End If
        End If
    End If

    On Error GoTo ErrHandler
    Debug.Print "基准面: " & IIf(swFeat Is Nothing And Not foundPlane, "[FAIL]", "[PASS]")

    ' ====== 切除 ======
    Debug.Print vbCrLf & "=== 切除 ==="
    If Not foundPlane Then
        Debug.Print "基准面未找到，跳过切除"
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

        ' FeatureCut(20参) 回退
        If swFeat Is Nothing Then
            swModel.InsertSketch2 True
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
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
