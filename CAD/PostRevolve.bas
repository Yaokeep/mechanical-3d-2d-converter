Option Explicit

' PostRevolve.bas - Chamfers + Fillets + Keyways
' All units in METERS (MKS document)

Sub main()
    Dim swApp As Object, swModel As Object
    Dim swFeatMgr As Object, swSketchMgr As Object
    Dim swFeat As Object, swSelMgr As Object
    Dim xv As Double, yv As Double, nSel As Long
    Dim x1 As Double, x2 As Double, y As Double
    Dim hw As Double, zNeg As Double, zPos As Double, dM As Double

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
    ' 端面倒角 C1.2
    ' ============================================

    ' Chamfer-LeftEnd
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", -0.233066, 0.016, 0.001, True, 0, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel > 0 Then
        Set swFeat = swFeatMgr.InsertFeatureChamfer(
            1, 1, 0.785, 0.0012#, 0, 0, 0, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-LeftEnd"
    End If

    ' Chamfer-RightEnd
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "", "Edge", 0.22173400000000001, 0.02, 0.001, True, 0, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel > 0 Then
        Set swFeat = swFeatMgr.InsertFeatureChamfer(
            1, 1, 0.785, 0.0012#, 0, 0, 0, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-RightEnd"
    End If

    ' ============================================
    ' 阶跃过渡圆角 R1.2
    ' ============================================
    swModel.ClearSelection2 True
    ' Step 1: X=-0.15786599999999998, R=0.0185
    swModel.Extension.SelectByID2 "", "Edge", -0.15786599999999998, 0.0185, 0.001, True, 1, Nothing, 0
    ' Step 2: X=-0.107866, R=0.02
    swModel.Extension.SelectByID2 "", "Edge", -0.107866, 0.02, 0.001, True, 1, Nothing, 0
    ' Step 3: X=-0.084866, R=0.023
    swModel.Extension.SelectByID2 "", "Edge", -0.084866, 0.023, 0.001, True, 1, Nothing, 0
    ' Step 4: X=0.080134, R=0.025
    swModel.Extension.SelectByID2 "", "Edge", 0.080134, 0.025, 0.001, True, 1, Nothing, 0
    ' Step 5: X=0.08733400000000001, R=0.025
    swModel.Extension.SelectByID2 "", "Edge", 0.08733400000000001, 0.025, 0.001, True, 1, Nothing, 0
    ' Step 6: X=0.17233400000000001, R=0.0215
    swModel.Extension.SelectByID2 "", "Edge", 0.17233400000000001, 0.0215, 0.001, True, 1, Nothing, 0
    nSel = swSelMgr.GetSelectedObjectCount2(-1)
    If nSel > 0 Then
        Set swFeat = swFeatMgr.FeatureFillet3(
            195, 0.0012#, 0, 0, False, 0, False, False)
        If Not swFeat Is Nothing Then swFeat.Name = "Fillet-Transitions"
    End If

    ' ============================================
    ' 键槽
    ' ============================================

    ' Keyway 1: Xc=-196.27mm L=40mm W=10mm D=5mm R=16mm

    ' Step 1: 相切参考面（上视基准面偏移 R）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.016#, 0, 0, 0, 0)
    If Not swFeat Is Nothing Then swFeat.Name = "KeywayPlane-1"

    ' Step 2: 键槽轮廓（XZ 平面，Y=shaft_r）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "KeywayPlane-1", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True
    x1 = -0.21626599999999999#
    x2 = -0.17626599999999998#
    y  = 0.016#
    hw = 0.005#
    zNeg = -hw : zPos = hw
    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg
    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos
    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos
    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg

    ' Step 3: 拉伸切除（Flip=True 向 -Y 轴心）
    dM = 0.005#
    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, dM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If Not swFeat Is Nothing Then swFeat.Name = "Keyway-1"

    ' Keyway 2: Xc=129.73mm L=38mm W=12mm D=6mm R=22mm

    ' Step 1: 相切参考面（上视基准面偏移 R）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "上视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    Set swFeat = swFeatMgr.InsertRefPlane(8, 0.0215#, 0, 0, 0, 0)
    If Not swFeat Is Nothing Then swFeat.Name = "KeywayPlane-2"

    ' Step 2: 键槽轮廓（XZ 平面，Y=shaft_r）
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "KeywayPlane-2", "PLANE", 0, 0, 0, True, 0, Nothing, 0
    swModel.InsertSketch2 True
    x1 = 0.110734#
    x2 = 0.148734#
    y  = 0.0215#
    hw = 0.006#
    zNeg = -hw : zPos = hw
    swSketchMgr.CreateLine x1, y, zNeg, x2, y, zNeg
    swSketchMgr.CreateLine x2, y, zNeg, x2, y, zPos
    swSketchMgr.CreateLine x2, y, zPos, x1, y, zPos
    swSketchMgr.CreateLine x1, y, zPos, x1, y, zNeg

    ' Step 3: 拉伸切除（Flip=True 向 -Y 轴心）
    dM = 0.006#
    Set swFeat = swFeatMgr.FeatureCut3( True, True, False, False, 0, dM, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If Not swFeat Is Nothing Then swFeat.Name = "Keyway-2"

    ' --- 完成 ---
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2
End Sub
