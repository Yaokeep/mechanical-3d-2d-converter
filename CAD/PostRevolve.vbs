' PostRevolve.vbs - Direct COM post-revolve features
Option Explicit

Dim swApp, swModel, swFeatMgr, swSketchMgr, swSelMgr, swFeat
Dim nSel, i, dM, hw

' --- Connect to SW ---
Set swApp = GetObject(, "SldWorks.Application")
If swApp Is Nothing Then
    WScript.Echo "ERR: Cannot connect to SW"
    WScript.Quit 1
End If
Set swModel = swApp.ActiveDoc
If swModel Is Nothing Then
    WScript.Echo "ERR: No active document"
    WScript.Quit 1
End If
Set swFeatMgr = swModel.FeatureManager
Set swSketchMgr = swModel.SketchManager
Set swSelMgr = swModel.SelectionManager

' ============================================
' 1. End Chamfers
' ============================================
' Chamfer-LeftEnd: X=-233.1mm R=16.0mm C1.2
swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "Edge", -0.233066, 0.016, 0.0, True, 0, Nothing, 0
nSel = swSelMgr.GetSelectedObjectCount2(-1)
If nSel > 0 Then
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.0012, 0.7853981633974483, 0, 0, 0, False)
    If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-LeftEnd"
End If
' Chamfer-RightEnd: X=221.7mm R=20.0mm C1.2
swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "Edge", 0.22173400000000001, 0.02, 0.0, True, 0, Nothing, 0
nSel = swSelMgr.GetSelectedObjectCount2(-1)
If nSel > 0 Then
    Set swFeat = swFeatMgr.InsertFeatureChamfer(1, 1, 0.0012, 0.7853981633974483, 0, 0, 0, False)
    If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-RightEnd"
End If

' ============================================
' 2. Step Fillets R1.20000000014403
' ============================================
swModel.ClearSelection2 True
swModel.Extension.SelectByID2 "", "Edge", -0.15786599999999998, 0.0185, 0.0, True, 1, Nothing, 0
swModel.Extension.SelectByID2 "", "Edge", -0.107866, 0.02, 0.0, True, 1, Nothing, 0
swModel.Extension.SelectByID2 "", "Edge", -0.084866, 0.023, 0.0, True, 1, Nothing, 0
swModel.Extension.SelectByID2 "", "Edge", 0.080134, 0.025, 0.0, True, 1, Nothing, 0
swModel.Extension.SelectByID2 "", "Edge", 0.08733400000000001, 0.025, 0.0, True, 1, Nothing, 0
swModel.Extension.SelectByID2 "", "Edge", 0.17233400000000001, 0.0215, 0.0, True, 1, Nothing, 0
nSel = swSelMgr.GetSelectedObjectCount2(-1)
If nSel >= 6 Then
    Set swFeat = swFeatMgr.FeatureFillet3(195, 0.00120000000014403, 0, 0, False, 0, False, False)
    If Not swFeat Is Nothing Then swFeat.Name = "Fillet-Transitions"
End If

' ============================================
' 3. Keyways ¡ª skipped (handled by Python COM)
' ============================================

' --- Done ---
swModel.ForceRebuild3 False
swModel.ViewZoomtofit2
WScript.Echo "OK"
