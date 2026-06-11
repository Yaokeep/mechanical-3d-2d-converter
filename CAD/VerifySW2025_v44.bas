Option Explicit

' ============================================================
' v44: 只修圆角 — 多种选边方式 + Options 值测试
' v43 结果: 6/7 PASS, 仅 Fillet 失败 (选边坐标在面上)
' ============================================================

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim swSelMgr As Object
Dim bn As Long

Sub main()
    On Error GoTo ErrHandler
    Set swApp = Application.SldWorks
    swApp.Visible = True
    Debug.Print "SW: " & swApp.RevisionNumber
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "请先 Ctrl+N 新建零件！", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ============================================================
    ' 0. 圆柱体 R=0.015, L=0.1
    ' ============================================================
    Debug.Print vbCrLf & "=== 0.圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.015, 0
    swSketchMgr.CreateLine 0, 0.015, 0, 0.1, 0.015, 0
    swSketchMgr.CreateLine 0.1, 0.015, 0, 0.1, 0, 0
    swSketchMgr.CreateLine 0.1, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.1, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 1. Extrusion2 凸台 (Y=0.008~0.018 跨表面, X=0.03~0.06, Z±0.005)
    ' ============================================================
    Debug.Print vbCrLf & "=== 1.Extrusion2 凸台 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.03, 0.008, 0, 0.06, 0.008, 0
    swSketchMgr.CreateLine 0.06, 0.008, 0, 0.06, 0.018, 0
    swSketchMgr.CreateLine 0.06, 0.018, 0, 0.03, 0.018, 0
    swSketchMgr.CreateLine 0.03, 0.018, 0, 0.03, 0.008, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.005, 0.005, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Boss"
    On Error GoTo ErrHandler

    ' ============================================================
    ' 现在做圆角测试
    ' 策略A: 选凸台顶面的边 (Y=0.018, Z=0.005, X=0.045)
    '         这是凸台最顶上的矩形棱边，100% 存在
    ' ============================================================
    Debug.Print vbCrLf & "=== 圆角测试 ==="

    ' --- A: Options=1 (简单等半径), 选凸台顶边 ---
    Debug.Print "--- A: Edge + Options=1 ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0.045, 0.018, 0.005, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        Dim selCount As Long
        selCount = swSelMgr.GetSelectedObjectCount2(-1)
        Debug.Print "  选中对象数=" & selCount
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(1, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet-A=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-A"
    End If
    On Error GoTo ErrHandler

    ' --- B: Options=195 (验证过的值), 同样选边 ---
    Debug.Print "--- B: Edge + Options=195 ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "EDGE", 0.045, 0.018, 0.004, False, 0, Nothing, 0
    Debug.Print "  选边 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet-B=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-B"
    End If
    On Error GoTo ErrHandler

    ' --- C: 选凸台侧面 FACE + Options=195 ---
    Debug.Print "--- C: Face + Options=195 ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    ' 凸台侧面在 Z=0.005 平面, 选点 (0.045, 0.012, 0.005)
    swModel.Extension.SelectByID2 "", "FACE", 0.045, 0.012, 0.005, False, 0, Nothing, 0
    Debug.Print "  选面 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet-C=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-C"
    End If
    On Error GoTo ErrHandler

    ' --- D: 选圆柱面 + Options=195 (v23验证过的方式) ---
    Debug.Print "--- D: CylFace + Options=195 ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 0.05, 0.015, 0, False, 0, Nothing, 0
    Debug.Print "  选面 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(195, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet-D=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-D"
    End If
    On Error GoTo ErrHandler

    ' --- E: 选凸台顶面 + Options=1 ---
    Debug.Print "--- E: TopFace + Options=1 ---"
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "FACE", 0.045, 0.018, 0, False, 0, Nothing, 0
    Debug.Print "  选面 Err=" & Err.Number
    If Err.Number = 0 Then
        bn = swModel.GetFeatureCount
        Set swFeat = Nothing
        Err.Clear
        Set swFeat = swFeatMgr.FeatureFillet3(1, 0.001, 0, 0, False, 0, False, False)
        Debug.Print "  Fillet-E=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-E"
    End If

    ' ============================================================
    ' 报告
    ' ============================================================
    On Error GoTo 0
    Debug.Print vbCrLf & "========== 报告 =========="
    Debug.Print "特征总数: " & swModel.GetFeatureCount
    Dim f As Object
    Dim j As Long
    For j = 1 To swModel.GetFeatureCount
        Set f = swModel.FeatureByPositionReverse(j)
        If Not f Is Nothing Then
            Debug.Print "  [" & j & "] " & f.Name
        End If
    Next
    swModel.ViewZoomtofit2
    MsgBox "v44 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub
