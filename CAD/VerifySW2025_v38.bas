Option Explicit

Dim swApp As Object
Dim swModel As Object
Dim swFeatMgr As Object
Dim swSketchMgr As Object
Dim swFeat As Object
Dim bn As Long

Sub setupLog()
    On Error Resume Next
    ' 输出到立即窗口 + 文件
End Sub

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

    ' === 0. 圆柱体基体 ===
    Debug.Print vbCrLf & "=== 0.圆柱体 ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0, 0, 0, 0, 0.01, 0
    swSketchMgr.CreateLine 0, 0.01, 0, 0.05, 0.01, 0
    swSketchMgr.CreateLine 0.05, 0.01, 0, 0.05, 0, 0
    swSketchMgr.CreateLine 0.05, 0, 0, 0, 0, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, False, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  Revolve2=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If swFeat Is Nothing Then MsgBox "圆柱体失败!", vbCritical: Exit Sub
    swFeat.Name = "Cylinder"
    On Error GoTo ErrHandler

    ' === 1. Extrusion2(23参) 参数值调试 ===
    ' 假设: 21.StartOffset, 22.StartOffsetDistance(Double), 23.FlipStartOffset
    Debug.Print vbCrLf & "=== 1.Extrusion2(23) 参数调试 ==="
    TestExt2Variant 1, True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False
    TestExt2Variant 2, True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, True, 0.005, False
    TestExt2Variant 3, True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, True
    TestExt2Variant 4, True, False, False, 0, 0, 0.01, 0.01, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False

    ' === 2. FeatureExtrusion3(26参) 测试 ===
    Debug.Print vbCrLf & "=== 2.FeatureExtrusion3(26参) ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.07, 0, -0.005, 0.07, 0, 0.005
    swSketchMgr.CreateLine 0.07, 0, 0.005, 0.07, 0.012, 0.005
    swSketchMgr.CreateLine 0.07, 0.012, 0.005, 0.07, 0.012, -0.005
    swSketchMgr.CreateLine 0.07, 0.012, -0.005, 0.07, 0, -0.005
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion3(True, False, False, 0, 0, 0.02, 0.02, False, False, False, False, 0#, 0#, False, False, 0#, 0#, False, True, False, False, False, False, 0, 0#, 0#)
    Debug.Print "  Extrusion3(26)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext3-26"
    On Error GoTo ErrHandler

    ' === 3. Cut3(26参) 参数值调试 ===
    Debug.Print vbCrLf & "=== 3.Cut3(26) 参数调试 ==="
    TestCut3Variant 1, True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False
    TestCut3Variant 2, True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, True
    ' 试试 Merge=True, 最后的 Boolean 变体
    TestCut3Variant 3, True, False, False, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, True, False, False, False
    ' 试试 Direction 反转
    TestCut3Variant 4, True, False, True, False, 0, 0.006, False, 0, 0.006, False, False, 0#, 0#, False, False, False, False, False, True, True, True, False, False, False, False

    ' === 4. RevolveCut 确保几何相交 ===
    Debug.Print vbCrLf & "=== 4.RevolveCut 相交测试 ==="
    On Error Resume Next
    ' 在圆柱体表面上方的矩形 (Y方向, 确保切除区域与圆柱体重叠)
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    ' 矩形在圆柱体内部: X=0.02~0.04, Y=0.002~0.008 (圆柱体 Y=0~0.01)
    swSketchMgr.CreateLine 0.02, 0.002, 0, 0.04, 0.002, 0
    swSketchMgr.CreateLine 0.04, 0.002, 0, 0.04, 0.008, 0
    swSketchMgr.CreateLine 0.04, 0.008, 0, 0.02, 0.008, 0
    swSketchMgr.CreateLine 0.02, 0.008, 0, 0.02, 0.002, 0
    swSketchMgr.CreateCenterLine 0, 0, 0, 0.05, 0, 0
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureRevolve2(True, True, False, True, False, False, 0, 0, 6.28318530717958, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True)
    Debug.Print "  RevolveCut+CL=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "RevolveCut"
    On Error GoTo ErrHandler

    ' === 5. 尝试用 FeatureExtrusion2 做切除 ===
    Debug.Print vbCrLf & "=== 5.Extrusion2 做切除(23参) ==="
    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.005, 0.01, -0.003, 0.02, 0.01, -0.003
    swSketchMgr.CreateLine 0.02, 0.01, -0.003, 0.02, 0.01, 0.003
    swSketchMgr.CreateLine 0.02, 0.01, 0.003, 0.005, 0.01, 0.003
    swSketchMgr.CreateLine 0.005, 0.01, 0.003, 0.005, 0.01, -0.003
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    ' 23参数: 假设最后3个是 StartOffset(Boolean), OffsetDistance(Double), FlipOffset(Boolean)
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, 0.006, 0.006, False, False, False, False, 0#, 0#, False, False, 0#, 0#, True, True, True, False, 0#, False)
    Debug.Print "  Ext2-Cut-like(23)=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext2Cut"
    On Error GoTo ErrHandler

    ' === 报告 ===
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
    MsgBox "v38 完成！Ctrl+G 看结果", vbInformation
    Exit Sub

ErrHandler:
    Debug.Print "!!! Err #" & Err.Number & ": " & Err.Description
    On Error Resume Next
    swModel.InsertSketch2 True
    Resume Next
End Sub

' ========== 辅助子程序 ==========

Sub TestExt2Variant(v As Long, _
    p1 As Boolean, p2 As Boolean, p3 As Boolean, p4 As Long, p5 As Long, _
    p6 As Double, p7 As Double, p8 As Boolean, p9 As Boolean, p10 As Boolean, _
    p11 As Boolean, p12 As Double, p13 As Double, p14 As Boolean, p15 As Boolean, _
    p16 As Double, p17 As Double, p18 As Boolean, p19 As Boolean, p20 As Boolean, _
    p21 As Boolean, p22 As Double, p23 As Boolean)

    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "右视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.05, 0, -0.005, 0.05, 0, 0.005
    swSketchMgr.CreateLine 0.05, 0, 0.005, 0.05, 0.012, 0.005
    swSketchMgr.CreateLine 0.05, 0.012, 0.005, 0.05, 0.012, -0.005
    swSketchMgr.CreateLine 0.05, 0.012, -0.005, 0.05, 0, -0.005
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureExtrusion2(p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17, p18, p19, p20, p21, p22, p23)
    Debug.Print "  Ext2_v" & v & "=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Ext2-v" & v
End Sub

Sub TestCut3Variant(v As Long, _
    p1 As Boolean, p2 As Boolean, p3 As Boolean, p4 As Boolean, _
    p5 As Long, p6 As Double, p7 As Boolean, p8 As Long, p9 As Double, _
    p10 As Boolean, p11 As Boolean, p12 As Double, p13 As Double, _
    p14 As Boolean, p15 As Boolean, p16 As Boolean, p17 As Boolean, _
    p18 As Boolean, p19 As Boolean, p20 As Boolean, p21 As Boolean, _
    p22 As Boolean, p23 As Boolean, p24 As Boolean, p25 As Boolean, p26 As Boolean)

    On Error Resume Next
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSketchMgr.CreateLine 0.005, 0.01, -0.003, 0.02, 0.01, -0.003
    swSketchMgr.CreateLine 0.02, 0.01, -0.003, 0.02, 0.01, 0.003
    swSketchMgr.CreateLine 0.02, 0.01, 0.003, 0.005, 0.01, 0.003
    swSketchMgr.CreateLine 0.005, 0.01, 0.003, 0.005, 0.01, -0.003
    swModel.InsertSketch2 True
    bn = swModel.GetFeatureCount
    Set swFeat = Nothing
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3(p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17, p18, p19, p20, p21, p22, p23, p24, p25, p26)
    Debug.Print "  Cut3_v" & v & "=" & IIf(swFeat Is Nothing, "FAIL", "PASS") & " Err=" & Err.Number & " feat=" & bn & "->" & swModel.GetFeatureCount
    If Not swFeat Is Nothing Then swFeat.Name = "Cut3-v" & v
End Sub
