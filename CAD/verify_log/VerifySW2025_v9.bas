Option Explicit

' VerifySW2025 v9 - 修复: IsSolid=True (实体), 正确退出草图, 倒角参数
' v8: FeatureRevolve2 草图打开时调用 → PASS (但生成了曲面)
' v9: IsSolid=True 生成实体, 修复 Chamfer 参数类型, 草图打开时旋转

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim boolstatus As Boolean

Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber

    Set swPart = swApp.ActiveDoc
    If swPart Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
    End If
    Set swModel = swPart
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Debug.Print "Test1 [PASS] 零件: " & swModel.GetTitle

    ' ====== Test2: 创建草图 ======
    Debug.Print vbCrLf & "=== Test2: 创建草图 ==="
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0

    On Error Resume Next
    swModel.InsertSketch2 True
    Debug.Print "InsertSketch2: Err=" & Err.Number
    On Error GoTo ErrHandler

    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Debug.Print "Test2 [PASS] 草图OK (矩形+中心线, 草图打开中)"

    ' ====== Test3: FeatureRevolve2 — 草图打开时直接旋转 (IsSolid=True) ======
    Debug.Print vbCrLf & "=== Test3: FeatureRevolve2 ==="

    ' 关键: IsSolid=True (第二个参数)
    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, True, False, False, False, False, _
        0, 0, 6.28318530717958, 0, _
        False, False, 0.01, 0.01, _
        0, 0, 0, True, True, True)
    Debug.Print "  方式A-IsSolid=True(20参数): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name & " | 类型: " & swFeat.GetTypeName2

    ' 方式B: 如果失败，尝试不同参数组合
    If swFeat Is Nothing Then
        Err.Clear
        swModel.InsertSketch2 True  ' 退出
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
        swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
        swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
        swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
        swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0

        Set swFeat = swFeatMgr.FeatureRevolve2( _
            True, True, False, False, False, False, _
            0, 0, 6.28318530717958, 0, _
            False, False, 0, 0, _
            True, True, True, 0, 0)
        Debug.Print "  方式B-18参数IsSolid=True: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    On Error GoTo ErrHandler

    If swFeat Is Nothing Then
        Debug.Print "Test3 [FAIL]"
        MsgBox "Test3 失败！", vbExclamation: Exit Sub
    End If
    swFeat.Name = "Test-Revolve"
    Debug.Print "Test3 [PASS]"

    ' ====== Test4: InsertFeatureChamfer — 实体倒角 ======
    Debug.Print vbCrLf & "=== Test4: InsertFeatureChamfer ==="

    ' 现在有实体了，在顶部边缘做倒角
    ' 选旋转体外圆柱面上的一条边
    swModel.ClearSelection2 True

    ' 方式A: SelectByRay 选圆柱顶部边
    swModel.Extension.SelectByRay 25, 10, -0.001, 25, 10, 0.001, 0.0001, 2, True, 0, Nothing
    Debug.Print "  选中边: " & swModel.SelectionManager.GetSelectedObjectCount2(-1)

    On Error Resume Next
    ' 尝试 InsertFeatureChamfer: 角度-距离 (type=1), 角度=45deg(0.785rad), 距离=0.001m=1mm
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 2, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "  方式A-Chamfer(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name

    ' 方式B: 试试7参数
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, -0.001, 25, 10, 0.001, 0.0001, 2, True, 0, Nothing

        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 2, 0.785, 0.001, 0#, 0#, 0#)
        Debug.Print "  方式B-Chamfer(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    ' 方式C: 试试用角度-距离 0.001m
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, -0.001, 25, 10, 0.001, 0.0001, 2, True, 0, Nothing

        Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 1, 0#, 0.001, 0#, 0#, 0#, False)
        Debug.Print "  方式C-Chamfer(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    ' 方式D: 试试SW旧版 FeatureChamfer
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, -0.001, 25, 10, 0.001, 0.0001, 2, True, 0, Nothing
        Set swFeat = swFeatMgr.FeatureChamfer(1, 0.001, 0.001, 0, 0, 0, 0, 0, 0)
        Debug.Print "  方式D-FeatureChamfer(9): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then Debug.Print "  特征名: " & swFeat.Name
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test4 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test5: FeatureFillet3 ======
    Debug.Print vbCrLf & "=== Test5: FeatureFillet3 ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 0, 10, -0.001, 0, 10, 0.001, 0.0001, 2, True, 0, Nothing
    Debug.Print "  选中边: " & swModel.SelectionManager.GetSelectedObjectCount2(-1)
    On Error Resume Next
    Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
    Debug.Print "FeatureFillet3(8): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Fillet"
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: InsertRefPlane ======
    Debug.Print vbCrLf & "=== Test6: InsertRefPlane ==="
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    On Error Resume Next
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: FeatureCut3 ======
    Debug.Print vbCrLf & "=== Test7: FeatureCut3 ==="
    If swFeat Is Nothing Then
        Debug.Print "Test7 [SKIP]"
    Else
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        On Error Resume Next
        swModel.InsertSketch2 True
        If Err.Number <> 0 Then Err.Clear: swSketchMgr.InsertSketch
        On Error GoTo ErrHandler
        swSketchMgr.CreateLine 10, 10, -3, 30, 10, -3
        swSketchMgr.CreateLine 30, 10, -3, 30, 10, 3
        swSketchMgr.CreateLine 30, 10, 3, 10, 10, 3
        swSketchMgr.CreateLine 10, 10, 3, 10, 10, -3
        On Error Resume Next
        swModel.InsertSketch2 True
        If Err.Number <> 0 Then Err.Clear: swSketchMgr.InsertSketch
        On Error GoTo ErrHandler
        Set swFeat = swFeatMgr.FeatureCut3(True, False, False, 0, 0, 0.003, 0.003, _
            False, False, False, False, 0#, 0#, False, False, False, False, False, _
            True, True, False, False, False, 0, 0#, False)
        Debug.Print "FeatureCut3(26): " & IIf(swFeat Is Nothing, "Nothing", "OK")
        If Not swFeat Is Nothing Then swFeat.Name = "Test-Cut"
        Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation

    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    MsgBox "错误 #" & Err.Number & ": " & Err.Description, vbCritical
End Sub
