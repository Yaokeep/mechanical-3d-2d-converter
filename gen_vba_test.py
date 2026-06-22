"""Generate simplest VBA test - just FeatureCut3 on Front Plane."""
import os

lines = []
lines.append('Option Explicit')
lines.append('Sub main()')
lines.append('    Dim swApp As Object, swModel As Object')
lines.append('    Dim swFM As Object, swSM As Object, swFeat As Object')
lines.append('    Dim fso As Object, f As Object, r As String')
lines.append('    ')
lines.append('    Set swApp = Application.SldWorks')
lines.append('    Set swModel = swApp.ActiveDoc')
lines.append('    If swModel Is Nothing Then')
lines.append('        Set fso = CreateObject("Scripting.FileSystemObject")')
lines.append('        Set f = fso.CreateTextFile("C:\\Users\\yaoshuo\\AppData\\Local\\Temp\\sw_vba_test_result.txt", True)')
lines.append('        f.WriteLine "ERR:NoDoc" : f.Close : Exit Sub')
lines.append('    End If')
lines.append('    Set swFM = swModel.FeatureManager')
lines.append('    Set swSM = swModel.SketchManager')
lines.append('    ')

# Select Front Plane using ChrW for Chinese chars
lines.append('    swModel.ClearSelection2 True')
lines.append('    On Error Resume Next')
lines.append('    swModel.Extension.SelectByID2 ChrW(21069)&ChrW(35270)&ChrW(22522)&ChrW(20934)&ChrW(38754), "PLANE", 0, 0, 0, False, 0, Nothing, 0')
lines.append('    swModel.InsertSketch2 True')

# Draw rectangle (10mm x 5mm, in meters for MKS)
lines.append('    swSM.CreateLine -0.01, 0.005, 0, 0.01, 0.005, 0')
lines.append('    swSM.CreateLine 0.01, 0.005, 0, 0.01, 0.015, 0')
lines.append('    swSM.CreateLine 0.01, 0.015, 0, -0.01, 0.015, 0')
lines.append('    swSM.CreateLine -0.01, 0.015, 0, -0.01, 0.005, 0')

# Test FeatureCut3
lines.append('    Set swFeat = swFM.FeatureCut3( True, True, False, False, 0, 0.002, False, 0, 0, False, False, 0, 0, False, False, False, False, False, True, True, True, False, 0, True, True, True )')
lines.append('    If Err.Number <> 0 Then')
lines.append('        r = "FeatureCut3: ERR " & Err.Description')
lines.append('    ElseIf swFeat Is Nothing Then')
lines.append('        r = "FeatureCut3: Nothing"')
lines.append('    Else')
lines.append('        swFeat.Name = "TestCut3"')
lines.append('        r = "FeatureCut3: OK"')
lines.append('    End If')
lines.append('    On Error GoTo 0')
lines.append('    ')

# Write result
lines.append('    Set fso = CreateObject("Scripting.FileSystemObject")')
lines.append('    Set f = fso.CreateTextFile("C:\\Users\\yaoshuo\\AppData\\Local\\Temp\\sw_vba_test_result.txt", True)')
lines.append('    f.WriteLine r : f.Close')
lines.append('End Sub')

os.makedirs('CAD', exist_ok=True)
with open('CAD/SimpleTest.bas', 'w', encoding='gbk') as f:
    f.write('\r\n'.join(lines))
print('Generated: CAD/SimpleTest.bas')
print('Please close any SW dialogs first, then in terminal:')
print('  python run_simple_test.py')
