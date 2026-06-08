Option Explicit

Sub main()
    Dim swApp As Object
    Dim swModel As Object
    Dim swSketchMgr As Object
    Dim swFeatMgr As Object
    Dim swFeat As Object

    Set swApp = Application.SldWorks
    swApp.Visible = True

    Set swModel = swApp.NewDocument(swApp.GetDocumentTemplate(12), 0, 0, 0)
    If swModel Is Nothing Then
        MsgBox "Cannot create part"
        Exit Sub
    End If

    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' Sketch on Front Plane
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch True

    ' Simple rectangle profile: 100mm long, 20mm radius
    With swSketchMgr
        .CreateLine2 -50, 0, 0, -50, 20, 0
        .CreateLine2 -50, 20, 0, 50, 20, 0
        .CreateLine2 50, 20, 0, 50, 0, 0
        .CreateLine2 50, 0, 0, -50, 0, 0
        .CreateCenterLine2 -50, 0, 0, 50, 0, 0
    End With

    swSketchMgr.InsertSketch True

    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, False, False, False, False, _
        0, 0, 2 * 3.14159265358979, 0, False, _
        0, False, True, True)

    If swFeat Is Nothing Then
        MsgBox "Revolve failed"
    Else
        swFeat.Name = "TestCylinder"
        swModel.ViewZoomtofit2
        MsgBox "OK - Cylinder created"
    End If
End Sub
