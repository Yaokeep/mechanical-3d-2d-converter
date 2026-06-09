Option Explicit

' VerifySW2025 v10 - 系统测试 InsertFeatureChamfer 签名 (7/8参数)
' v9: Test3 PASS (IsSolid=True)
' v10: 5种 Chamfer 调用方式, 先打印选中信息

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object

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

    ' ====== Test2+3: 创建实体旋转体 ======
    Debug.Print vbCrLf & "=== Test2+3: 创建实体旋转体 ==="
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

    ' ====== Test4: InsertFeatureChamfer 签名测试 ======
    Debug.Print vbCrLf & "=== Test4: InsertFeatureChamfer ==="

    ' 选实体的外圆柱边: 射线 (25, 10, 0) 方向沿 Z
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
    Debug.Print "  选中 " & swModel.SelectionManager.GetSelectedObjectCount2(-1) & " 条边"

    ' 方式1: 8参数 (0, 2, ...)
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 2, 0#, 0#, 0.001, 0#, 0#, False)
    Debug.Print "  1) 8参(0,2,...): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    If Err.Number <> 0 Then Debug.Print "     -> " & Err.Description

    ' 方式2: 7参数 (0, 1, ...)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
        Set swFeat = swFeatMgr.InsertFeatureChamfer(0, 1, 0#, 0#, 0.001, 0#, 0#)
        Debug.Print "  2) 7参(0,1,...): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Err.Number <> 0 Then Debug.Print "     -> " & Err.Description
    End If

    ' 方式3: 8参数 Type=1(角度距离), Width=1
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
        Debug.Print "  3) 8参(1,1,...): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Err.Number <> 0 Then Debug.Print "     -> " & Err.Description
    End If

    ' 方式4: 7参数 Type=1
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
        Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#)
        Debug.Print "  4) 7参(1,1,...): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Err.Number <> 0 Then Debug.Print "     -> " & Err.Description
    End If

    ' 方式5: 旧版 FeatureChamfer
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByRay 25, 10, 0, 25, 10, 0.01, 0.001, 2, True, 0, Nothing
        Set swFeat = swFeatMgr.FeatureChamfer(1, 0.001, 0.001, 0, 0, 0, 0, 0, 0)
        Debug.Print "  5) FeatureChamfer(9): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
        If Err.Number <> 0 Then Debug.Print "     -> " & Err.Description
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test4 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
    MsgBox "错误 #" & Err.Number & ": " & Err.Description, vbCritical
End Sub
