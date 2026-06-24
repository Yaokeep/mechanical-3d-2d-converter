Option Explicit

' PostRevolve.bas - Chamfers + Fillets + Keyways
' All units in METERS (MKS document)

Sub main()
    Dim swApp As Object, swModel As Object
    Dim swFeatMgr As Object, swSketchMgr As Object
    Dim swFeat As Object, swSelMgr As Object
    Dim nSel As Long, i As Long
    Dim x1 As Double, x2 As Double, y1 As Double, y2 As Double
    Dim halfW As Double, halfL As Double, dM As Double

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "No active document!", vbCritical
        Exit Sub
    End If
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager
    Set swSelMgr = swModel.SelectionManager

    ' ============================================
    ' End Chamfers C1.2
    ' ============================================

    ' Chamfer-LeftEnd
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", -0.233066, 0.016, 0.0, True, 0, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel > 0 Then
        Set swFeat = swFeatMgr.InsertFeatureChamfer(
            1, 1, 0.785, 0.0012#, 0, 0, 0, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-LeftEnd"
    End If

    ' Chamfer-RightEnd
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", 0.22173400000000001, 0.02, 0.0, True, 0, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel > 0 Then
        Set swFeat = swFeatMgr.InsertFeatureChamfer(
            1, 1, 0.785, 0.0012#, 0, 0, 0, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-RightEnd"
    End If

    ' ============================================
    ' Step Fillets R1.2
    ' ============================================
    swModel.ClearSelection2 True
    ' Step 1: X=-0.15786599999999998, R=0.0185
    swModel.Extension.SelectByID2 "", "Edge", -0.15786599999999998, 0.0185, 0.0, True, 1, Nothing, 0
    ' Step 2: X=-0.107866, R=0.02
    swModel.Extension.SelectByID2 "", "Edge", -0.107866, 0.02, 0.0, True, 1, Nothing, 0
    ' Step 3: X=-0.084866, R=0.023
    swModel.Extension.SelectByID2 "", "Edge", -0.084866, 0.023, 0.0, True, 1, Nothing, 0
    ' Step 4: X=0.080134, R=0.025
    swModel.Extension.SelectByID2 "", "Edge", 0.080134, 0.025, 0.0, True, 1, Nothing, 0
    ' Step 5: X=0.08733400000000001, R=0.025
    swModel.Extension.SelectByID2 "", "Edge", 0.08733400000000001, 0.025, 0.0, True, 1, Nothing, 0
    ' Step 6: X=0.17233400000000001, R=0.0215
    swModel.Extension.SelectByID2 "", "Edge", 0.17233400000000001, 0.0215, 0.0, True, 1, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel >= 6 Then
        Set swFeat = swFeatMgr.FeatureFillet3(
            195, 0.0012#, 0, 0, False, 0, False, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-Transitions"
    End If

    ' ============================================
    ' Keyways (Front Plane + FeatureExtrusion2)
    ' ============================================

    ' Keyway 1: X=[-216.3,-176.3] W=10 D=5 R=16

    ' Step 1: Sketch on Front Plane
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' Keyway profile (XY plane, extrude along Z)
    x1 = -0.21626599999999999#
    x2 = -0.17626599999999998#
    y1 = 0.011#
    y2 = 0.016#
    swSketchMgr.CreateCornerRectangle x1, y1, 0, x2, y2, 0

    ' Step 2: FeatureExtrusion2 bidirectional Z
    halfW = 0.005#
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, halfW, halfW, False, False, False, False, 0, 0, False, False, False, False, True, True, True, 0, 0, False)
    If Not swFeat Is Nothing Then
        swFeat.Name = "Keyway-1"
    End If

    ' Keyway 2: X=[110.7,148.7] W=12 D=6 R=22

    ' Step 1: Sketch on Front Plane
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True

    ' Keyway profile (XY plane, extrude along Z)
    x1 = 0.110734#
    x2 = 0.148734#
    y1 = 0.0155#
    y2 = 0.0215#
    swSketchMgr.CreateCornerRectangle x1, y1, 0, x2, y2, 0

    ' Step 2: FeatureExtrusion2 bidirectional Z
    halfW = 0.006#
    Set swFeat = swFeatMgr.FeatureExtrusion2(True, False, False, 0, 0, halfW, halfW, False, False, False, False, 0, 0, False, False, False, False, True, True, True, 0, 0, False)
    If Not swFeat Is Nothing Then
        swFeat.Name = "Keyway-2"
    End If

    ' --- Done ---
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2
End Sub
