Option Explicit

' VerifySW2025 v14 - 精确匹配 Fillet/RefPlane 参数个数
' v13: FeatureFillet2(16) OK+Err450, FeatureRefPlane(6) OK+Err438

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object, tmp As Object

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

    ' ====== Test5: FeatureFillet2 参数个数探查 ======
    Debug.Print vbCrLf & "=== Test5: FeatureFillet2 参数个数 ==="

    ' F2-1: 14参 (去掉最后2个)
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    Debug.Print "F2-1(14参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' F2-2: 12参
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "F2-2(12参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' F2-3: 10参
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "F2-3(10参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' F2-4: 8参
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0)
        Debug.Print "F2-4(8参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' F2-5: 11参 (SW2025最常见的奇数)
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "F2-5(11参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' F2-6: 13参
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "F2-6(13参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: FeatureRefPlane 参数个数探查 ======
    Debug.Print vbCrLf & "=== Test6: FeatureRefPlane 参数个数 ==="

    ' R1-1: FeatureRefPlane(4参)
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear: Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0)
    Debug.Print "R1-1(4参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' R1-2: FeatureRefPlane(5参)
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0)
        Debug.Print "R1-2(5参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' R1-3: InsertRefPlane(4参) Type=8
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0)
        Debug.Print "R1-3-InsertRefPlane(4): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' R1-4: InsertRefPlane(5参)
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0)
        Debug.Print "R1-4-InsertRefPlane(5): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' R1-5: 用 Front Plane
    If Err.Number <> 0 Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "R1-5-FeatureRefPlane(Front,6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: FeatureCut3 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="
    If swFeat Is Nothing Then
        Debug.Print "Test7 [SKIP]"
    Else
        Dim planeName As String: planeName = "Test-Plane"
        swFeat.Name = planeName

        ' 在基准面上画草图+切除
        On Error Resume Next
        swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
        swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
        swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
        swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3
        swModel.InsertSketch2 True
        Err.Clear
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "T7-FeatureCut3(26): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

        ' FeatureCut 回退
        If swFeat Is Nothing Then
            Err.Clear
            swModel.Extension.SelectByID2 planeName, "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 20, 10, -3, 30, 10, -3
            swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
            swSketchMgr.CreateLine 30, 10, 3, 20, 10, 3
            swSketchMgr.CreateLine 20, 10, 3, 20, 10, -3
            swModel.InsertSketch2 True
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, 0, 0, 0.003, 0.003, _
                False, False, False, False, 0#, 0#, False, False, False, False)
            Debug.Print "T7-FeatureCut(18): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        On Error GoTo ErrHandler
        If Not swFeat Is Nothing Then swFeat.Name = "Test-Cut"
        Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
