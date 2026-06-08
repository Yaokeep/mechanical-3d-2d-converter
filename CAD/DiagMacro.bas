Option Explicit

' Diagnostic: create sketch ONLY, no revolve
' Check if sketch looks correct in SolidWorks first

Sub main()
    Dim swApp As Object, swModel As Object
    Dim swSketchMgr As Object

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "Please open a new part first (Ctrl+N)", vbCritical
        Exit Sub
    End If
    Set swSketchMgr = swModel.SketchManager

    ' Sketch on Front Plane
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch2 True

    ' Profile: half-section of stepped shaft
    With swSketchMgr
        .CreateLine2 -233.066, 0, 0, -233.066, 16, 0
        .CreateLine2 -233.066, 16, 0, -158.466, 16, 0
        .CreateLine2 -158.466, 16, 0, -157.866, 16, 0
        .CreateLine2 -157.866, 16, 0, -157.866, 18.5, 0
        .CreateLine2 -157.866, 18.5, 0, -108.466, 18.5, 0
        .CreateLine2 -108.466, 18.5, 0, -107.866, 18.5, 0
        .CreateLine2 -107.866, 18.5, 0, -107.866, 20, 0
        .CreateLine2 -107.866, 20, 0, -85.466, 20, 0
        .CreateLine2 -85.466, 20, 0, -84.866, 20, 0
        .CreateLine2 -84.866, 20, 0, -84.866, 23, 0
        .CreateLine2 -84.866, 23, 0, 79.534, 23, 0
        .CreateLine2 79.534, 23, 0, 80.134, 23, 0
        .CreateLine2 80.134, 23, 0, 80.134, 25, 0
        .CreateLine2 80.134, 25, 0, 86.734, 25, 0
        .CreateLine2 86.734, 25, 0, 87.334, 25, 0
        .CreateLine2 87.334, 25, 0, 87.334, 21.5, 0
        .CreateLine2 87.334, 21.5, 0, 171.734, 21.5, 0
        .CreateLine2 171.734, 21.5, 0, 172.334, 21.5, 0
        .CreateLine2 172.334, 21.5, 0, 172.334, 20, 0
        .CreateLine2 172.334, 20, 0, 221.734, 20, 0
        .CreateLine2 221.734, 20, 0, 221.734, 0, 0
        .CreateLine2 221.734, 0, 0, -233.066, 0, 0
        .CreateCenterLine2 -233.066, 0, 0, 221.734, 0, 0
    End With

    swModel.ViewZoomtofit2
    MsgBox "Sketch created." & vbCrLf & vbCrLf & _
           "Check in Feature Tree: Sketch1" & vbCrLf & _
           "Does the profile look correct?" & vbCrLf & _
           "Is it fully closed? Is the centerline (dash-dot) at Y=0?", _
           vbInformation, "Diagnostic - Step 1"
End Sub
