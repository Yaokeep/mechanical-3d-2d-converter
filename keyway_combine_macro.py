"""Generate and run SW VBA macro to boolean-subtract keyway bodies from shaft.

Python COM cannot create Cut features (FeatureCut3/4 return None).
Workaround: generate a VBA macro that runs InsertCombineFeature,
then execute it via SolidWorks COM.
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SRC_PATH = PROJECT_ROOT / "src"
for p in [str(PROJECT_ROOT), str(SRC_PATH)]:
    if p not in sys.path:
        sys.path.insert(0, p)

VBA_MACRO = r"""Option Explicit

' Auto-generated: Keyway Boolean Subtract Macro
' Subtracts keyway bodies from the main shaft body.

Sub main()
    Dim swApp As Object
    Dim swModel As Object
    Dim swFeatMgr As Object
    Dim swFeat As Object
    Dim bodies As Object
    Dim i As Integer
    Dim nBodies As Long
    Dim mainBody As Object
    Dim kwBody As Object
    Dim mainIndex As Long
    Dim kwIndices As String

    Set swApp = Application.SldWorks
    Set swModel = swApp.ActiveDoc
    If swModel Is Nothing Then
        MsgBox "No active document!", vbCritical
        Exit Sub
    End If

    Set swFeatMgr = swModel.FeatureManager

    ' Get solid bodies
    Set bodies = swModel.GetBodies2(0)  ' 0 = swAllBodies
    If bodies Is Nothing Then
        MsgBox "No bodies found!", vbCritical
        Exit Sub
    End If

    nBodies = UBound(bodies) + 1
    Debug.Print "Total bodies: " & nBodies

    If nBodies < 2 Then
        MsgBox "Need at least 2 bodies (shaft + keyway)! Found: " & nBodies, vbInformation
        Exit Sub
    End If

    ' Find main body (largest volume) and keyway bodies
    Dim maxVol As Double
    maxVol = 0
    mainIndex = -1

    For i = 0 To nBodies - 1
        Dim body As Object
        Set body = bodies(i)
        ' Body is returned as a dispatch object, need to get IBody2
        ' Get body volume using GetMassProperties
        Dim vol As Double
        On Error Resume Next
        vol = body.GetMassProperties(0).Volume
        On Error GoTo 0

        Debug.Print "Body " & i & ": volume=" & vol

        If vol > maxVol Then
            maxVol = vol
            mainIndex = i
        End If
    Next i

    If mainIndex = -1 Then
        MsgBox "Could not identify main body!", vbCritical
        Exit Sub
    End If

    Debug.Print "Main body index: " & mainIndex & " (volume=" & maxVol & ")"

    ' Subtract each keyway body from the main body
    For i = 0 To nBodies - 1
        If i <> mainIndex Then
            Debug.Print "Subtracting body " & i & " from body " & mainIndex
            swModel.ClearSelection2 True

            ' Select main body
            swModel.Extension.SelectByID2 "", "SOLIDBODY", 0, 0, 0, True, 0, Nothing, 0

            ' Try to select keyway body by selecting at its position
            ' For keyways, they're at the top of the shaft

            ' Select the body to subtract
            Dim selOK As Boolean
            selOK = swModel.Extension.SelectByID2("", "SOLIDBODY", 0, 0.01, 0, True, 1, Nothing, 0)

            Dim selCount As Long
            selCount = swModel.Extension.GetSelectionCount2(-1)
            Debug.Print "  Selected " & selCount & " items for boolean"

            If selCount >= 2 Then
                On Error Resume Next
                Set swFeat = swFeatMgr.InsertCombineFeature(1, Nothing, Nothing)  ' 1 = Subtract
                On Error GoTo 0

                If Not swFeat Is Nothing Then
                    swFeat.Name = "Keyway-" & (i)
                    Debug.Print "  [OK] Keyway-" & i & " subtracted!"
                Else
                    Debug.Print "  [FAIL] InsertCombineFeature returned Nothing for body " & i
                End If
            Else
                Debug.Print "  [SKIP] Could not select " & selCount & " bodies (need 2)"
            End If
        End If
    Next i

    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2

    MsgBox "Keyway boolean subtract completed!" & vbCrLf & _
           "Check the feature tree for Keyway-* features.", vbInformation, "Done"
End Sub
"""


def run_keyway_combine():
    """Generate VBA macro, load it, and run it in SolidWorks."""
    from win32com.client import Dispatch

    # 1. Save VBA macro to disk
    macro_path = PROJECT_ROOT / "soldwork" / "KeywayCombine.bas"
    macro_path.parent.mkdir(exist_ok=True)
    macro_path.write_text(VBA_MACRO, encoding="ascii", errors="replace")
    print(f"VBA macro saved: {macro_path}")

    # 2. Connect to SW and run the macro
    sw = Dispatch("SldWorks.Application")

    # Method 1: RunMacro2
    macro_str = str(macro_path.absolute())
    try:
        result = sw.RunMacro(macro_str, "main", 0)
        print(f"RunMacro result: {result}")
        if result == 0:
            print("[OK] Macro executed successfully!")
            return True
        else:
            print(f"[WARN] RunMacro returned {result}")
    except Exception as e:
        print(f"RunMacro error: {e}")

    # Method 2: Load and run via IMacque interface
    try:
        import pythoncom
        pythoncom.CoInitialize()
        sw.UnloadMacro(macro_str)  # Unload if previously loaded
        loaded = sw.LoadAndRunMacro2(macro_str, "main", "")
        print(f"LoadAndRunMacro2: {loaded}")
        if loaded:
            print("[OK] Macro loaded and executed!")
            return True
    except Exception as e:
        print(f"LoadAndRunMacro2 error: {e}")

    # Method 3: Try OpenDoc6 approach
    try:
        sw.RunMacro2(macro_str, "main", "main", 0)
        print("[OK] RunMacro2 executed!")
        return True
    except Exception as e:
        print(f"RunMacro2 error: {e}")

    return False


if __name__ == "__main__":
    ok = run_keyway_combine()
    if not ok:
        print("\nManual steps in SW:")
        print("  1. Insert > Features > Combine")
        print("  2. Operation: Subtract")
        print("  3. Main body: select shaft")
        print("  4. Bodies to subtract: select keyway bodies")
