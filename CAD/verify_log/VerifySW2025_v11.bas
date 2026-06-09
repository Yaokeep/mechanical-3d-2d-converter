Option Explicit

' VerifySW2025 v11 - 先定位 SelectByRay，再测倒角
' v10: SelectByRay 在 Extension 上导致 Error 13
' v11: 测试 Extension.SelectByRay vs SelectionManager.SelectByRay

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object

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
    Set swSelMgr = swModel.SelectionManager
    Debug.Print "Test1 [PASS] 零件: " & swModel.GetTitle

    ' ====== 创建实体旋转体 ======
    Debug.Print vbCrLf & "=== 创建实体旋转体 ==="
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
        False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " | " & swFeat.Name
    If swFeat Is Nothing Then MsgBox "旋转失败", vbCritical: Exit Sub

    ' ====== TestA: SelectByRay 位置测试 ======
    Debug.Print vbCrLf & "=== TestA: SelectByRay 位置 ==="

    ' A1: Extension.SelectByRay (11参数)
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
    Debug.Print "A1-Extension(11参): Err=" & Err.Number & " 选中=" & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True

    ' A2: Extension.SelectByRay (12参数, 加 SelectOption)
    Err.Clear
    swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing, 0
    Debug.Print "A2-Extension(12参): Err=" & Err.Number & " 选中=" & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True

    ' A3: SelectionManager.SelectByRay (10参数)
    Err.Clear
    swSelMgr.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0
    Debug.Print "A3-SelectionMgr(10参): Err=" & Err.Number & " 选中=" & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True

    ' A4: SelectionManager.SelectByRay (11参数, 加 Callout)
    Err.Clear
    swSelMgr.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
    Debug.Print "A4-SelectionMgr(11参): Err=" & Err.Number & " 选中=" & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True

    ' A5: 用 SelectByID2 选一条边
    Err.Clear
    swModel.Extension.SelectByID2 "", "EDGE", 25, 10, 0, True, 0, Nothing, 0
    Debug.Print "A5-SelectByID2(EDGE): Err=" & Err.Number & " 选中=" & swSelMgr.GetSelectedObjectCount2(-1)
    swModel.ClearSelection2 True

    On Error GoTo ErrHandler

    ' ====== Test4: 用正确的方式选边+倒角 ======
    Debug.Print vbCrLf & "=== Test4: Chamfer (用正确方式选边) ==="

    ' 用能工作的方式先选边
    On Error Resume Next
    swModel.ClearSelection2 True

    ' 尝试 SelectByID2 选中边
    swModel.Extension.SelectByID2 "", "EDGE", 25, 10, 0, True, 0, Nothing, 0
    Debug.Print "选边: Err=" & Err.Number & " n=" & swSelMgr.GetSelectedObjectCount2(-1)

    ' Chamfer 尝试
    Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "Chamfer(8参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    If swFeat Is Nothing And Err.Number = 0 Then
        ' Err=0 但 Nothing: 可能是选边问题，尝试不选边直接对圆柱端面倒角
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "Chamfer(8参,边2): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    If swFeat Is Nothing And Err.Number = 0 Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "Chamfer(8参,边3): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 尝试 FeatureChamfer 旧版
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", 25, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureChamfer(1, 0.001, 0.001, 0, 0, 0, 0, 0, 0)
        Debug.Print "FeatureChamfer(9): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then
        Debug.Print "Test4 [PASS] feat=" & swFeat.Name
    Else
        Debug.Print "Test4 [FAIL]"
    End If

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
