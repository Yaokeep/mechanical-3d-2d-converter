Option Explicit

' VerifySW2025 v22 - 倒角OK! 精调圆角选边坐标 + 基准面参数
' v21: Chamfer PASS. Fillet: 选边(0,10,0)→0条. RefPlane: Nothing

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

    ' ====== Test4: 倒角 (已验证OK的签名) ======
    Debug.Print vbCrLf & "=== Test4: 倒角 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 50, 10, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.785, 0.001, 0#, 0#, 0#, False)
    Debug.Print "倒角: " & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number
    On Error GoTo ErrHandler

    ' ====== Test5: 圆角 — 多点尝试选边 ======
    Debug.Print vbCrLf & "=== Test5: 圆角 — 选边遍历 ==="
    On Error Resume Next

    ' 尝试不同坐标选边 (左端面X=0的圆形边)
    Dim coords(7, 2) As Double
    coords(0, 0) = 0:  coords(0, 1) = 10:  coords(0, 2) = 0    ' 顶部
    coords(1, 0) = 0:  coords(1, 1) = 0:   coords(1, 2) = 10   ' 前侧
    coords(2, 0) = 0:  coords(2, 1) = -10: coords(2, 2) = 0    ' 底部
    coords(3, 0) = 0:  coords(3, 1) = 0:   coords(3, 2) = -10  ' 后侧
    coords(4, 0) = 25: coords(4, 1) = 10:  coords(4, 2) = 0    ' 圆柱体顶部中点
    coords(5, 0) = 50: coords(5, 1) = 10:  coords(5, 2) = 0    ' 右端面顶部
    coords(6, 0) = 25: coords(6, 1) = 0:   coords(6, 2) = 10   ' 中间前侧
    coords(7, 0) = 25: coords(7, 1) = 5:   coords(7, 2) = 5    ' 中间45度

    Dim i As Integer, cx As Double, cy As Double, cz As Double
    For i = 0 To 7
        cx = coords(i, 0): cy = coords(i, 1): cz = coords(i, 2)
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "", "EDGE", cx, cy, cz, False, 0, Nothing, 0
        Debug.Print "  边(" & cx & "," & cy & "," & cz & "): n=" & swSelMgr.GetSelectedObjectCount2(-1)
        If swSelMgr.GetSelectedObjectCount2(-1) > 0 Then
            ' 找到边了，尝试圆角
            Set swFeat = Nothing: Err.Clear
            Set swFeat = swFeatMgr.FeatureFillet3(0, 0.0005, 0, 0, True, 0, True, True)
            Debug.Print "    → Fillet3: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
            If Not swFeat Is Nothing Then Exit For
        End If
    Next i

    On Error GoTo ErrHandler
    Debug.Print "圆角: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test6: 基准面 ======
    Debug.Print vbCrLf & "=== Test6: 基准面 ==="
    On Error Resume Next

    ' T6-1: Front Plane 偏移 (Y方向偏移10mm)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swFeat = Nothing: Err.Clear
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0, 0)
    Debug.Print "T6-1 Front+offset10: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' T6-2: Top Plane 偏移5mm
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.005, 0, 0, 0, 0)
        Debug.Print "T6-2 Top+offset5: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-3: Right Plane 偏移
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Right Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.025, 0, 0, 0, 0)
        Debug.Print "T6-3 Right+offset25: " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-4: InsertRefPlane 5参 (8, offset, 0, 0, 0)
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0, 0, 0)
        Debug.Print "T6-4 InsertRefPlane(5): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' T6-5: InsertRefPlane 7参
    If swFeat Is Nothing Then
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        Set swFeat = Nothing: Err.Clear
        Set swFeat = swFeatMgr.InsertRefPlane(8, 0.01, 0#, 0#, 0#, 0#, 0#)
        Debug.Print "T6-5 InsertRefPlane(7dbl): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    Debug.Print "基准面: " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    ' ====== Test7: 切除 ======
    Debug.Print vbCrLf & "=== Test7: 切除 ==="
    If swFeat Is Nothing Then
        Debug.Print "基准面失败，跳过切除"
    Else
        swFeat.Name = "Test-Plane"
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
