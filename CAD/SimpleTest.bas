Option Explicit
Sub main()
    Dim swApp As Object, swModel As Object
    Dim swFM As Object, swSM As Object, swFeat As Object
    Dim fso As Object, f As Object, r As String
    
    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        Set fso = CreateObject("Scripting.FileSystemObject")
        Set f = fso.CreateTextFile("C:\Users\yaoshuo\AppData\Local\Temp\sw_vba_test_result.txt", True)
        f.WriteLine "ERR:NoDoc" : f.Close : Exit Sub
    End If
    Set swFM = swModel.FeatureManager
    Set swSM = swModel.SketchManager
    
    swModel.ClearSelection2 True
    On Error Resume Next
    swModel.Extension.SelectByID2 ChrW(21069)&ChrW(35270)&ChrW(22522)&ChrW(20934)&ChrW(38754), "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swModel.InsertSketch2 True
    swSM.CreateLine -0.01, 0.005, 0, 0.01, 0.005, 0
    swSM.CreateLine 0.01, 0.005, 0, 0.01, 0.015, 0
    swSM.CreateLine 0.01, 0.015, 0, -0.01, 0.015, 0
    swSM.CreateLine -0.01, 0.015, 0, -0.01, 0.005, 0
    Set swFeat = swFM.FeatureCut3( True, True, False, False, 0, 0.002, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )
    If Err.Number <> 0 Then
        r = "FeatureCut3: ERR " & Err.Description
    ElseIf swFeat Is Nothing Then
        r = "FeatureCut3: Nothing"
    Else
        swFeat.Name = "TestCut3"
        r = "FeatureCut3: OK"
    End If
    On Error GoTo 0
    
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set f = fso.CreateTextFile("C:\Users\yaoshuo\AppData\Local\Temp\sw_vba_test_result.txt", True)
    f.WriteLine r : f.Close
End Sub