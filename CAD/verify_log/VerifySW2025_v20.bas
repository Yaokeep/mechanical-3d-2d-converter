Option Explicit

' VerifySW2025 v20 - 验证选边是否真实有效，然后逐个创建特征
' 关键发现: SelectByID2("","EDGE",...) 选边可能不可靠

Dim swApp As Object, swModel As Object
Dim swFeatMgr As Object, swSketchMgr As Object
Dim swFeat As Object, swSelMgr As Object
Dim swSelData As Object

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks: swApp.Visible = True
    Debug.Print "SW版本: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then MsgBox "请先 Ctrl+N 新建零件！", vbCritical: Exit Sub
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
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    ' ====== TestA: 选边 — 获取选中边的几何信息 ======
    Debug.Print vbCrLf & "=== TestA: 选边并获取几何信息 ==="
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Debug.Print "选中数量: " & swSelMgr.GetSelectedObjectCount2(-1)

    ' 尝试获取选中的对象
    If swSelMgr.GetSelectedObjectCount2(-1) > 0 Then
        Set swSelData = swSelMgr.GetSelectedObject6(1, -1)
        If swSelData Is Nothing Then
            Debug.Print "GetSelectedObject6(1): Nothing"
        Else
            Debug.Print "选中对象类型: " & swSelData.ObjectType
        End If
    Else
        Debug.Print "未选中任何对象！"
    End If
    On Error GoTo ErrHandler

    ' ====== TestB: 用 FeatureManager 直接创建倒角特征 ======
    Debug.Print vbCrLf & "=== TestB: 倒角 ==="
    On Error Resume Next

    ' B1: 选边 → InsertFeatureChamfer
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Dim selCountB As Long: selCountB = swSelMgr.GetSelectedObjectCount2(-1)
    Debug.Print "B1-选边: " & selCountB

    If selCountB > 0 Then
        Err.Clear
        Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, 0#)
        Debug.Print "B1-Chamfer(8): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Not swFeat Is Nothing Then swFeat.Name = "Test-Chamfer"
    End If

    ' B2: 不选边，直接选面 → 倒角面的边
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "FACE", 50, 5, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, 0#)
        Debug.Print "B2-选面后Chamfer: feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' B3: FeatureChamfer 旧版
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureChamfer(2, 0.001, 0.001, 0, 0, 0, 0, 0, 0)
        Debug.Print "B3-FeatureChamfer(9): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' B4: 选择圆柱体顶面 → 自动倒角所有外圆边
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "FACE", 25, 10, 0, False, 0, Nothing, 0
        Debug.Print "  选面: " & swSelMgr.GetSelectedObjectCount2(-1)
        Set swFeat = swFeatMgr.FeatureChamfer(2, 0.001, 0.001, 0, 0, 0, 0, 0, 0)
        Debug.Print "B4-FaceChamfer(9): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== TestC: 圆角 ======
    Debug.Print vbCrLf & "=== TestC: 圆角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True

    ' C1: 选端面圆边
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Debug.Print "C1-选边: " & swSelMgr.GetSelectedObjectCount2(-1)

    Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    Debug.Print "C1-Fillet(14): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' C2: 选圆柱面
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "FACE", 25, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "C2-选面Fillet(14): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' C3: FeatureFillet3 (8参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
        Debug.Print "C3-Fillet3(8): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== TestD: 基准面 ======
    Debug.Print vbCrLf & "=== TestD: 基准面 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "D1-RefPlane(6): feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Plane"
    On Error GoTo ErrHandler
    Debug.Print "基准面: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== TestE: 切除 ======
    Debug.Print vbCrLf & "=== TestE: 切除 ==="
    If swFeat Is Nothing Then
        Debug.Print "基准面失败，跳过切除"
    Else
        On Error Resume Next
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Test-Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 20, 0, -4, 30, 0, -4
        swSketchMgr.CreateLine 30, 0, -4, 30, 0, 4
        swSketchMgr.CreateLine 30, 0, 4, 20, 0, 4
        swSketchMgr.CreateLine 20, 0, 4, 20, 0, -4

        ' E1: FeatureCut3 草图打开时
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
        Debug.Print "E1-Cut3: feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

        ' E2: FeatureCut 草图退出后
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
            Err.Clear
            Set swFeat = swFeatMgr.FeatureCut(True, False, False, False, 0, 0.005, 0.005, _
                False, False, False, False, 0#, 0#, False, False, False, False)
            Debug.Print "E2-FeatureCut: feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        ' E3: 从 Front Plane 切除
        If swFeat Is Nothing Then
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 22, 4, 0, 28, 4, 0
            swSketchMgr.CreateLine 28, 4, 0, 28, 8, 0
            swSketchMgr.CreateLine 28, 8, 0, 22, 8, 0
            swSketchMgr.CreateLine 22, 8, 0, 22, 4, 0
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
            Debug.Print "E3-FrontCut3: feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        ' E4: FeatureCut4
        If swFeat Is Nothing Then
            swModel.ClearSelection2 True
            swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
            swModel.InsertSketch2 True
            swSketchMgr.CreateLine 22, 4, 0, 28, 4, 0
            swSketchMgr.CreateLine 28, 4, 0, 28, 8, 0
            swSketchMgr.CreateLine 28, 8, 0, 22, 8, 0
            swSketchMgr.CreateLine 22, 8, 0, 22, 4, 0
            Err.Clear
            Set swFeat = swFeatMgr.FeatureCut4(True, False, False, _
                False, 0, 0.005, _
                False, 0, 0.005, _
                False, False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, 0#, _
                False, False)
            Debug.Print "E4-Cut4: feat=" & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        End If

        On Error GoTo ErrHandler
    End If
    Debug.Print "切除: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    On Error Resume Next
    swModel.InsertSketch2 True
    On Error GoTo 0
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
