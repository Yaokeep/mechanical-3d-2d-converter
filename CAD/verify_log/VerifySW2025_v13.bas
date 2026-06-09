Option Explicit

' VerifySW2025 v13 - Fillet/RefPlane 替代方法名测试
' Test5: FeatureFillet2, FeatureFillet, InsertFeatureFillet
' Test6: FeatureRefPlane, InsertRefPlane 不同参数

Dim swApp As Object, swModel As Object, swPart As Object
Dim swFeatMgr As Object, swSketchMgr As Object, swFeat As Object
Dim swSelMgr As Object

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
    Debug.Print "零件: " & swModel.GetTitle

    ' ====== 创建旋转体 ======
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 10, 0
    swSketchMgr.CreateLine 0, 10, 0, 50, 10, 0
    swSketchMgr.CreateLine 50, 10, 0, 50, 0, 0
    swSketchMgr.CreateLine 50, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 50, 0, 0
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "旋转体: " & IIf(swFeat Is Nothing, "FAIL", "PASS")

    ' ====== Test5: Fillet 替代方法名 ======
    Debug.Print vbCrLf & "=== Test5: Fillet ==="

    ' T5-1: FeatureFillet2 (旧版, 可能仍存在)
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
    Err.Clear
    Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    Debug.Print "T5-1 FeatureFillet2(16): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T5-2: FeatureFillet2 少参数
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet2(0, 0.0005, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-2 FeatureFillet2(10): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-3: FeatureFillet 旧版 (7参)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-3 FeatureFillet(7): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-4: FeatureFillet 更多参数
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet(0.0005, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        Debug.Print "T5-4 FeatureFillet(13): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-5: FeatureFillet3 不同参数顺序
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 0, 10, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, False, 0, False, False)
        Debug.Print "T5-5 FeatureFillet3(Prop=False): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T5-6: 选圆柱中部边
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "", "EDGE", 25, 10, 0, False, 0, Nothing, 0
        Debug.Print "  T5-6 选边: n=" & swSelMgr.GetSelectedObjectCount2(-1)
        Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
        Debug.Print "T5-6 FeatureFillet3(中边): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test5 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: RefPlane 替代方法 ======
    Debug.Print vbCrLf & "=== Test6: RefPlane ==="

    ' T6-1: FeatureRefPlane (旧名, 6参)
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "T6-1 FeatureRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T6-2: InsertRefPlane(8, 0.001, False, False, False, False)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.001, False, False, False, False)
        Debug.Print "T6-2 InsertRefPlane(Boolean): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-3: InsertRefPlane(2, ...)  - 平行于屏幕?
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(2, 0, 0, 0, 0, 0)
        Debug.Print "T6-3 InsertRefPlane(2,平行): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-4: 用 Front Plane
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
        Debug.Print "T6-4 Front+InsertRefPlane(6): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-5: InsertRefPlane(8) 用更小偏移
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        Err.Clear
        swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.02, 0, 0, 0, 0)
        Debug.Print "T6-5 InsertRefPlane(offset=0.02): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "Test6 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
