Option Explicit

' CreateShaft v3 - Minimum API surface, maximum compatibility
' Steps: 1. Manual: File > New > Part (Ctrl+N)
'        2. Tools > Macro > New > Paste this > F5

Sub main()
    Dim swApp As Object, swModel As Object
    Dim swFeatMgr As Object, swSketchMgr As Object
    Dim swFeat As Object

    On Error Resume Next

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "Please create a new part first (Ctrl+N), then run this macro.", vbCritical
        Exit Sub
    End If

    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' =====================================================
    ' STEP 1: Revolve base body
    ' =====================================================
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch

    With swSketchMgr
        ' Left end face
        .CreateLine2 -233.066, 0, 0, -233.066, 16, 0
        ' Section 1 (R=16)
        .CreateLine2 -233.066, 16, 0, -158.466, 16, 0
        ' Step 1->2
        .CreateLine2 -158.466, 16, 0, -157.866, 16, 0
        .CreateLine2 -157.866, 16, 0, -157.866, 18.5, 0
        ' Section 2 (R=18.5)
        .CreateLine2 -157.866, 18.5, 0, -108.466, 18.5, 0
        ' Step 2->3
        .CreateLine2 -108.466, 18.5, 0, -107.866, 18.5, 0
        .CreateLine2 -107.866, 18.5, 0, -107.866, 20, 0
        ' Section 3 (R=20)
        .CreateLine2 -107.866, 20, 0, -85.466, 20, 0
        ' Step 3->4
        .CreateLine2 -85.466, 20, 0, -84.866, 20, 0
        .CreateLine2 -84.866, 20, 0, -84.866, 23, 0
        ' Section 4 (R=23)
        .CreateLine2 -84.866, 23, 0, 79.534, 23, 0
        ' Step 4->5
        .CreateLine2 79.534, 23, 0, 80.134, 23, 0
        .CreateLine2 80.134, 23, 0, 80.134, 25, 0
        ' Section 5 (R=25)
        .CreateLine2 80.134, 25, 0, 86.734, 25, 0
        ' Step 5->6
        .CreateLine2 86.734, 25, 0, 87.334, 25, 0
        .CreateLine2 87.334, 25, 0, 87.334, 21.5, 0
        ' Section 6 (R=21.5)
        .CreateLine2 87.334, 21.5, 0, 171.734, 21.5, 0
        ' Step 6->7
        .CreateLine2 171.734, 21.5, 0, 172.334, 21.5, 0
        .CreateLine2 172.334, 21.5, 0, 172.334, 20, 0
        ' Section 7 (R=20)
        .CreateLine2 172.334, 20, 0, 221.734, 20, 0
        ' Right end face
        .CreateLine2 221.734, 20, 0, 221.734, 0, 0
        ' Bottom edge back to start
        .CreateLine2 221.734, 0, 0, -233.066, 0, 0
        ' Centerline (revolve axis)
        .CreateCenterLine2 -233.066, 0, 0, 221.734, 0, 0
    End With

    ' Exit sketch
    swSketchMgr.InsertSketch
    swModel.ViewZoomtofit2

    ' --- Try revolve: FeatureRevolve (3 params) first ---
    Set swFeat = swFeatMgr.FeatureRevolve(6.28318530717959, False, True)

    ' --- If that failed, try FeatureRevolve2 ---
    If swFeat Is Nothing Then
        Err.Clear
        Set swFeat = swFeatMgr.FeatureRevolve2(True, False, False, False, False, _
            0, 0, 6.28318530717959, 0, False, 0, False, True, True)
    End If

    If swFeat Is Nothing Then
        Err.Clear
        Set swFeat = swFeatMgr.FeatureRevolve2(True, False, False, False, False, _
            0, 0, 6.28318530717959, 0, False, 0, False)
    End If

    If swFeat Is Nothing Then
        MsgBox "Revolve failed! The sketch should be visible." & vbCrLf & vbCrLf & _
               "Please try manually:" & vbCrLf & _
               "1. Select Sketch1 in feature tree" & vbCrLf & _
               "2. Click Revolved Boss/Base" & vbCrLf & _
               "3. Set axis = centerline, angle = 360" & vbCrLf & _
               "4. Click OK", vbExclamation
        Exit Sub
    End If

    swFeat.Name = "Revolve-ShaftBody"
    Debug.Print "[OK] Revolve-ShaftBody"

    ' =====================================================
    ' STEP 2: Chamfers (C1.2 both ends)
    ' =====================================================
    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay -233.066, 16, -1, -233.066, 16, 1, 0.001, 2, True, 0, Nothing
    If swModel.Extension.GetSelectionCount > 0 Then
        Set swFeat = swFeatMgr.FeatureChamfer(1, 0.0012, 0.0012)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-LeftEnd"
    End If

    swModel.ClearSelection2 True
    swModel.Extension.SelectByRay 221.734, 20, -1, 221.734, 20, 1, 0.001, 2, True, 0, Nothing
    If swModel.Extension.GetSelectionCount > 0 Then
        Set swFeat = swFeatMgr.FeatureChamfer(1, 0.0012, 0.0012)
        If Not swFeat Is Nothing Then swFeat.Name = "Chamfer-RightEnd"
    End If

    ' =====================================================
    ' STEP 3: Fillets - manual reminder
    ' =====================================================
    Debug.Print "Fillets: please add R1.2 fillets manually (6 step edges)"

    ' =====================================================
    ' STEP 4: Keyways
    ' =====================================================
    MakeKeyway -196.266, 40, 5, 16, 5, "Keyway-1"
    MakeKeyway 129.734, 38, 6, 21.5, 6, "Keyway-2"

    ' Done
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2
    MsgBox "Done!" & vbCrLf & vbCrLf & _
           "Features: Revolve-ShaftBody, Chamfer-LeftEnd, Chamfer-RightEnd, Keyway-1, Keyway-2" & vbCrLf & _
           "Add fillets: select 6 step edges > Fillet R1.2" & vbCrLf & _
           "Save as: SLDPRT", vbInformation, "CreateShaft"
End Sub


Private Sub MakeKeyway(cx, length, halfWidth, shaftR, depth, featName)
    Dim swPlane As Object, swFeat As Object
    Dim x1, x2, z1, z2

    x1 = cx - length / 2
    x2 = cx + length / 2
    z1 = -halfWidth
    z2 = halfWidth

    On Error Resume Next

    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swPlane = swFeatMgr.InsertRefPlane(8, shaftR / 1000, 0, 0, 0, 0)

    If swPlane Is Nothing Then Exit Sub
    swPlane.Name = featName & "-Plane"

    swSketchMgr.InsertSketch
    With swSketchMgr
        .CreateLine2 x1, shaftR, z1, x2, shaftR, z1
        .CreateLine2 x2, shaftR, z1, x2, shaftR, z2
        .CreateLine2 x2, shaftR, z2, x1, shaftR, z2
        .CreateLine2 x1, shaftR, z2, x1, shaftR, z1
    End With
    swSketchMgr.InsertSketch

    Set swFeat = swFeatMgr.FeatureCut2(True, False, depth / 1000, False, True)
    If Not swFeat Is Nothing Then swFeat.Name = featName
End Sub
