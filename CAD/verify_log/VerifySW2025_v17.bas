Option Explicit

' VerifySW2025 v17 - FeatureCut 最小化测试: 贯穿切除
' Test7 全部 Nothing → 可能是方向/端面条件问题

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

    ' ====== Test7: 从 Top Plane 贯穿切除 ======
    ' 圆柱体: X轴(0~50), 半径10mm(Y方向). Top Plane = XZ平面
    ' 在 Top Plane 上画矩形, 切除方向 = Y(上下)
    ' 矩形: X=15~35, Z=-5~5, 贯穿 (双向)
    Debug.Print vbCrLf & "=== Test7: 贯穿切除 ==="

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' 矩形 (在Top Plane = XZ平面, Y=0)
    swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
    swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
    swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
    swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5
    Debug.Print "  矩形 15~35 x -5~5 (草图打开)"

    ' 方式A: FeatureCut3 — ThroughAll双向 (endType=0)
    On Error Resume Next
    Err.Clear
    Set swFeat = swFeatMgr.FeatureCut3( _
        True, False, False, _          ' flip, flipDir, D1_D2_Opposite
        0, 0, 0#, _                    ' T1_Flip, T1_EndType(0=ThroughAll), T1_Depth
        0, 0, 0#, _                    ' T2_Flip, T2_EndType(0=ThroughAll), T2_Depth
        False, False, 0#, _            ' Draft1, DraftDir1, DraftAngle1
        False, 0#, _                   ' Draft2, DraftAngle2
        False, 0#, _                   ' T1_OffsetFlip, T1_OffsetDist
        False, 0#, _                   ' T2_OffsetFlip, T2_OffsetDist
        False, 0#, _                   ' T1_Translate, T1_TranslateDist
        False, 0#, _                   ' T2_Translate, T2_TranslateDist
        False, False, Nothing, False)   ' AutoSelect, FeatScope, FeatScopeBodies, AutoSelComp
    Debug.Print "A-Cut3(ThroughAll,双向,30参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number

    ' 方式B: FeatureCut3 — Blind 双向 3mm
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
        swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
        swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
        swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5

        Set swFeat = swFeatMgr.FeatureCut3( _
            False, False, False, _         ' flip=False, flipDir=False, opp=False
            False, 1, 0.005, _             ' T1_Flip, T1_EndType(1=Blind), T1_Depth(5mm)
            False, 1, 0.005, _             ' T2_Flip, T2_EndType(1=Blind), T2_Depth(5mm)
            False, False, 0#, _            ' Draft
            False, 0#, False, 0#, _         ' Draft2
            False, 0#, False, 0#, _         ' Offset
            False, 0#, False, 0#, _         ' Translate
            False, False, Nothing, False)    ' Scope
        Debug.Print "B-Cut3(Blind,5mm,30参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式C: FeatureCut5 (多一个旋转参数)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
        swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
        swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
        swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5

        Set swFeat = swFeatMgr.FeatureCut5( _
            False, False, False, _
            False, 1, 0.005, _
            False, 1, 0.005, _
            False, False, 0#, _
            False, 0#, False, 0#, _
            False, 0#, False, 0#, _
            False, 0#, False, 0#, _
            0, 0#, False, False)
        Debug.Print "C-Cut5(30参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式D: FeatureCut4
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
        swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
        swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
        swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5

        Set swFeat = swFeatMgr.FeatureCut4( _
            False, False, False, _
            False, 1, 0.005, _
            False, 1, 0.005, _
            False, False, 0#, _
            False, 0#, False, 0#, _
            False, 0#, False, 0#, _
            False, 0#, False, 0#, _
            False, False)
        Debug.Print "D-Cut4(28参): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    ' 方式E: FeatureCut (原始版, 18参数)
    If swFeat Is Nothing Then
        Err.Clear
        swModel.ClearSelection2 True
        swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
        swModel.InsertSketch2 True
        swSketchMgr.CreateLine 15, 0, -5, 35, 0, -5
        swSketchMgr.CreateLine 35, 0, -5, 35, 0, 5
        swSketchMgr.CreateLine 35, 0, 5, 15, 0, 5
        swSketchMgr.CreateLine 15, 0, 5, 15, 0, -5

        Set swFeat = swFeatMgr.FeatureCut( _
            True, False, False, False, 0, 0.005, 0.005, _
            False, False, False, False, 0#, 0#, False, False, False, False)
        Debug.Print "E-FeatureCut(18): " & IIf(swFeat Is Nothing, "Nothing", "OK") & " Err=" & Err.Number
    End If

    On Error GoTo ErrHandler
    If Not swFeat Is Nothing Then swFeat.Name = "Test-Cut"
    Debug.Print "Test7 " & IIf(swFeat Is Nothing, "[FAIL]", "[PASS]")

    swModel.ViewZoomtofit2
    MsgBox "测试完成！Ctrl+G 查看输出。", vbInformation
    Exit Sub
ErrHandler:
    Debug.Print "!!! 错误 #" & Err.Number & ": " & Err.Description
End Sub
