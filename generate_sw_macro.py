#!/usr/bin/env python
"""Generate SolidWorks VBA macro from DXF shaft parameters (ASCII only).

Usage:
    python generate_sw_macro.py
    Output: CAD/CreateShaftMacro.bas
"""

import os
import sys

# ============================================================================
# Shaft parameters extracted from DXF (unit: mm)
# ============================================================================
SECTIONS = [
    {"x_start": -233.066, "x_end": -158.466, "radius": 16.0},
    {"x_start": -157.266, "x_end": -108.466, "radius": 18.5},
    {"x_start": -107.266, "x_end":  -85.466, "radius": 20.0},
    {"x_start":  -84.266, "x_end":   79.534, "radius": 23.0},
    {"x_start":   80.734, "x_end":   86.734, "radius": 25.0},
    {"x_start":   87.934, "x_end":  171.734, "radius": 21.5},
    {"x_start":  172.934, "x_end":  221.734, "radius": 20.0},
]

KEYWAYS = [
    {"x_start": -216.266, "x_end": -176.266, "width": 10.0, "depth": 5.0, "shaft_radius": 16.0},
    {"x_start":  110.734, "x_end":  148.734, "width": 12.0, "depth": 6.0, "shaft_radius": 21.5},
]

CHAMFER_SIZE = 1.2
FILLET_R = 1.2


def generate_vba_module(output_path: str):
    left_x = SECTIONS[0]["x_start"]
    left_r = SECTIONS[0]["radius"]
    right_x = SECTIONS[-1]["x_end"]
    right_r = SECTIONS[-1]["radius"]

    # Step face X positions (midpoints of gaps between adjacent sections)
    step_x = []
    for i in range(len(SECTIONS) - 1):
        mid = (SECTIONS[i]["x_end"] + SECTIONS[i+1]["x_start"]) / 2.0
        step_x.append(mid)

    # Build half-profile contour lines
    sketch_lines = []

    def add_line(x1, y1, x2, y2):
        if abs(x2-x1) < 0.0005 and abs(y2-y1) < 0.0005:
            return
        sketch_lines.append((x1, y1, x2, y2))

    # Left end face: centerline to top
    add_line(left_x, 0.0, left_x, left_r)

    # Upper surface of all sections
    for i, s in enumerate(SECTIONS):
        r = s["radius"]
        if i == 0:
            add_line(left_x, r, s["x_end"], r)
        else:
            prev_step = step_x[i-1]
            prev_r = SECTIONS[i-1]["radius"]
            add_line(prev_step, prev_r, prev_step, r)
            add_line(prev_step, r, s["x_end"], r)
        if i < len(SECTIONS) - 1:
            add_line(s["x_end"], r, step_x[i], r)

    # Right end face: top to centerline
    add_line(right_x, right_r, right_x, 0.0)

    # Bottom closure: along centerline back to left
    add_line(right_x, 0.0, left_x, 0.0)

    # Generate CreateLine2 calls
    line_calls = []
    for x1, y1, x2, y2 in sketch_lines:
        line_calls.append(
            "        .CreateLine2 {:.6f}#, {:.6f}#, 0#, {:.6f}#, {:.6f}#, 0#".format(x1, y1, x2, y2)
        )

    # Generate step position / radius arrays for fillet selection
    step_pos_lines = []
    step_rad_lines = []
    for i, sx in enumerate(step_x):
        r_big = max(SECTIONS[i]["radius"], SECTIONS[i+1]["radius"])
        step_pos_lines.append("    stepX({}) = {:.6f}#".format(i+1, sx))
        step_rad_lines.append("    stepR({}) = {:.6f}#".format(i+1, r_big))

    # Build the complete VBA module as a plain string
    vba = r"""Attribute VB_Name = "CreateShaft"
Option Explicit

'============================================================================
' CreateShaft - Stepped Shaft Parametric Modeling Macro
'============================================================================
' Generates .sldprt with full editable feature tree:
'   1. Revolve-ShaftBody    - Revolve (main shaft body)
'   2. Chamfer-LeftEnd      - Left end chamfer C{chamfer:.1f}
'   3. Chamfer-RightEnd     - Right end chamfer C{chamfer:.1f}
'   4. Fillet-Transitions   - Step transition fillets R{fillet:.1f} (x{nsteps})
{keyway_list}
' Usage: Tools > Macro > New > Paste this code > Press F5 > Save as .sldprt
'============================================================================

Dim swApp       As SldWorks.SldWorks
Dim swModel     As ModelDoc2
Dim swPart      As PartDoc
Dim swFeatMgr   As FeatureManager
Dim swSketchMgr As SketchManager
Dim swFeat      As Feature
Dim boolStatus  As Boolean
Dim longStatus  As Long


' ===== MAIN =====
Sub main()
    On Error GoTo ErrHandler

    Set swApp = Application.SldWorks
    swApp.Visible = True
    swApp.UserControl = True

    ' Create new part document
    Set swPart = swApp.NewDocument( _
        swApp.GetDocumentTemplate(swDocPART, "", 0, 0, 0), 0, 0, 0)
    If swPart Is Nothing Then
        MsgBox "Cannot create new part document!", vbCritical
        Exit Sub
    End If
    Set swModel = swPart
    Set swFeatMgr = swModel.FeatureManager
    Set swSketchMgr = swModel.SketchManager

    ' Set MMGS unit system
    swModel.SetUserPreferenceIntegerValue swUnitSystem, 0

    ' Isometric view
    swModel.ShowNamedView2 "*Isometric", -1

    '----- Step 1: Revolve base body -----
    Debug.Print vbCrLf & "=== Step 1: Revolve-ShaftBody ==="
    CreateRevolveShaftBody

    '----- Step 2: End chamfers C{chamfer:.1f} -----
    Debug.Print vbCrLf & "=== Step 2: Chamfers ==="
    CreateEndChamfer {left_x:.6f}#, {left_r:.6f}#, {chamfer:.6f}#, "Chamfer-LeftEnd"
    CreateEndChamfer {right_x:.6f}#, {right_r:.6f}#, {chamfer:.6f}#, "Chamfer-RightEnd"

    '----- Step 3: Step transition fillets R{fillet:.1f} -----
    Debug.Print vbCrLf & "=== Step 3: Fillet-Transitions ==="
    CreateStepFillets

    '----- Step 4: Keyway cut-extrudes -----
    Debug.Print vbCrLf & "=== Step 4: Keyways ==="
{keyway_calls}
    '----- Finish -----
    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2

    MsgBox "Stepped shaft model created!" & vbCrLf & vbCrLf & _
           "Feature tree:" & vbCrLf & _
           "  1. Revolve-ShaftBody" & vbCrLf & _
           "  2. Chamfer-LeftEnd (C{chamfer:.1f})" & vbCrLf & _
           "  3. Chamfer-RightEnd (C{chamfer:.1f})" & vbCrLf & _
           "  4. Fillet-Transitions (R{fillet:.1f})" & vbCrLf & _
{keyway_msg}
           "" & vbCrLf & _
           "File > Save As > SLDPRT format", _
           vbInformation, "CreateShaft - Done"

    Exit Sub

ErrHandler:
    MsgBox "Error " & Err.Number & ": " & Err.Description & vbCrLf & _
           "Line: " & Erl, vbCritical, "Macro Error"
End Sub


' ===== CreateRevolveShaftBody =====
' Sketch half-profile on Front Plane (XY), revolve 360 deg around X-axis
Private Sub CreateRevolveShaftBody()
    swModel.Extension.SelectByID2 "Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    swSketchMgr.InsertSketch True

    With swSketchMgr
{line_block}
        ' Centerline along X-axis (revolve axis)
        .CreateCenterLine2 {left_x:.6f}#, 0#, 0#, {right_x:.6f}#, 0#, 0#
    End With

    swSketchMgr.InsertSketch True

    ' FeatureRevolve2: 360-degree full revolve
    Set swFeat = swFeatMgr.FeatureRevolve2( _
        True, False, False, False, False, False, _
        0, 0, 2 * 3.14159265358979, 0, _
        False, False, 0, 0, True, True, True, 0, 0)

    If swFeat Is Nothing Then
        Err.Raise vbObjectError + 1, , "Revolve feature failed! Check sketch."
    End If
    swFeat.Name = "Revolve-ShaftBody"
    Debug.Print "  [OK] Revolve-ShaftBody"
End Sub


' ===== CreateEndChamfer =====
' Apply distance-distance chamfer on end face circular edge
Private Sub CreateEndChamfer( _
    ByVal faceX As Double, ByVal radius As Double, _
    ByVal chamferSize As Double, ByVal featName As String)

    Dim edgeCount As Long

    swModel.ClearSelection2 True

    ' Select circular edge at end face
    ' Ray from (faceX, radius, -1) in +Z direction
    boolStatus = swModel.Extension.SelectByRay( _
        faceX, radius, -1#, faceX, radius, 1#, 0.0001, 2, True, 0, Nothing)

    edgeCount = swModel.Extension.GetSelectionCount
    Debug.Print "  " & featName & ": " & edgeCount & " edge(s) selected"

    If edgeCount > 0 Then
        ' FeatureChamfer type=1: distance-distance
        Set swFeat = swFeatMgr.FeatureChamfer( _
            1, chamferSize / 1000#, chamferSize / 1000#, 0, 0, 0, 0, 0, 0)
        If Not swFeat Is Nothing Then
            swFeat.Name = featName
            Debug.Print "  [OK] " & featName & " (C" & chamferSize & ")"
        Else
            Debug.Print "  [FAIL] " & featName
        End If
    Else
        Debug.Print "  [WARN] " & featName & " - no edge found, add C" & chamferSize & " chamfer manually"
    End If
End Sub


' ===== CreateStepFillets =====
' Select outer circular edges at each step face and apply R{fillet:.1f} fillet
Private Sub CreateStepFillets()
    Dim i As Integer
    Dim sx As Double, rBig As Double
    Dim stepX({nsteps}) As Double
    Dim stepR({nsteps}) As Double
    Dim edgeCount As Long, totalEdges As Long

{step_x_array}
{step_r_array}

    totalEdges = 0
    swModel.ClearSelection2 True

    For i = 1 To {nsteps}
        sx = stepX(i)
        rBig = stepR(i)

        ' Ray from (sx, rBig, -1) to (sx, rBig, 1) in +Z direction
        boolStatus = swModel.Extension.SelectByRay( _
            sx, rBig, -1#, sx, rBig, 1#, 0.0001, 2, True, 0, Nothing)

        If swModel.Extension.GetSelectionCount <= totalEdges Then
            ' Fallback: try slightly inward
            boolStatus = swModel.Extension.SelectByRay( _
                sx, rBig - 0.5, -1#, sx, rBig - 0.5, 1#, 0.0001, 2, True, 0, Nothing)
        End If

        totalEdges = swModel.Extension.GetSelectionCount
        Debug.Print "  Edge " & i & ": X=" & Format(sx, "0.0") & _
                    " R=" & Format(rBig, "0.0") & " (" & totalEdges & " total selected)"
    Next i

    If totalEdges >= {nsteps} Then
        Set swFeat = swFeatMgr.FeatureFillet({fillet_m:.6f}#, 1, 0, 0, 0, 0, 0)
        If Not swFeat Is Nothing Then
            swFeat.Name = "Fillet-Transitions"
            Debug.Print "  [OK] Fillet-Transitions (R{fillet:.1f}, " & totalEdges & " edges)"
        Else
            Debug.Print "  [WARN] FeatureFillet failed - add R{fillet:.1f} fillet manually"
        End If
    Else
        Debug.Print "  [WARN] Only " & totalEdges & " edges selected (need {nsteps})"
        Debug.Print "  [INFO] Manually select all step edges > Fillet R{fillet:.1f}"
    End If
End Sub


' ===== CreateKeywayFeature =====
' Create keyway by cut-extruding from a plane tangent to shaft top surface
' Parameters:
'   cx:        keyway center X coordinate
'   length:    keyway length along X-axis
'   halfWidth: keyway half-width along Z-axis
'   shaftR:    shaft radius (for tangent plane position)
'   depth:     keyway depth
'   featName:  feature name
Private Sub CreateKeywayFeature( _
    ByVal cx As Double, ByVal length As Double, _
    ByVal halfWidth As Double, ByVal shaftR As Double, _
    ByVal depth As Double, ByVal featName As String)

    Dim swPlane As Feature
    Dim planeName As String
    Dim x1 As Double, x2 As Double
    Dim z1 As Double, z2 As Double

    planeName = featName & "-Plane"
    x1 = cx - length / 2#
    x2 = cx + length / 2#
    z1 = -halfWidth
    z2 = halfWidth

    ' A: Create tangent plane at shaft top (Y = +shaftR)
    ' Shaft revolves around X-axis, top surface at Y = +shaftR (global)
    ' Tangent plane is parallel to XZ (Top Plane), offset by +shaftR along Y
    swModel.ClearSelection2 True
    swModel.Extension.SelectByID2 "Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0
    Set swPlane = swFeatMgr.InsertRefPlane(8, shaftR / 1000#, 0, 0, 0, 0)

    If swPlane Is Nothing Then
        Debug.Print "  [FAIL] " & featName & " - cannot create tangent plane"
        Exit Sub
    End If
    swPlane.Name = planeName
    Debug.Print "  " & featName & ": tangent plane Y=" & Format(shaftR, "0.0")

    ' B: Draw keyway rectangle on tangent plane
    swSketchMgr.InsertSketch True

    With swSketchMgr
        .CreateLine2 x1, shaftR, z1, x2, shaftR, z1  ' Front (Z=-halfWidth)
        .CreateLine2 x2, shaftR, z1, x2, shaftR, z2  ' Right (X=x2)
        .CreateLine2 x2, shaftR, z2, x1, shaftR, z2  ' Back  (Z=+halfWidth)
        .CreateLine2 x1, shaftR, z2, x1, shaftR, z1  ' Left  (X=x1)
    End With

    swSketchMgr.InsertSketch True

    ' C: Cut-extrude downward (-Y direction), depth = keyway depth
    Set swFeat = swFeatMgr.FeatureCut3( _
        True,       ' singleDirection
        False,      ' flipDirection
        False,      ' direction2
        0, 0,       ' d2 depths
        depth / 1000#, depth / 1000#, ' d1 depths (mm -> m)
        False, False, False, False, _  ' drafts
        0, 0,                          ' draft angles
        False, False, False, False, False, _
        True, True, True, True, 0, 0)

    If Not swFeat Is Nothing Then
        swFeat.Name = featName
        Debug.Print "  [OK] " & featName & _
                    " (L=" & Format(length, "0.0") & _
                    " W=" & Format(halfWidth * 2, "0.0") & _
                    " D=" & Format(depth, "0.0") & ")"
    Else
        Debug.Print "  [FAIL] " & featName & " - FeatureCut3"
    End If
End Sub
"""

    # Build keyway comment list and call list
    keyway_list_lines = []
    keyway_call_lines = []
    keyway_msg_lines = []
    for i, kw in enumerate(KEYWAYS):
        w = kw["width"]
        d = kw["depth"]
        sr = kw["shaft_radius"]
        cx = (kw["x_start"] + kw["x_end"]) / 2.0
        length = kw["x_end"] - kw["x_start"]
        hw = w / 2.0

        keyway_list_lines.append(
            "'   {}. Keyway-{}              - Keyway {:.0f}x{:.0f}mm".format(i+5, i+1, w, d))
        keyway_call_lines.append(
            "    CreateKeywayFeature {:.6f}#, {:.6f}#, {:.6f}#, {:.6f}#, {:.6f}#, \"Keyway-{}\"".format(
                cx, length, hw, sr, d, i+1))
        keyway_msg_lines.append(
            '           "  {}. Keyway-{} ({:.0f}x{:.0f}mm)" & vbCrLf & _'.format(i+5, i+1, w, d))

    nsteps = len(step_x)
    fillet_m = FILLET_R / 1000.0

    # Perform substitutions
    vba = vba.format(
        chamfer=CHAMFER_SIZE,
        fillet=FILLET_R,
        fillet_m=fillet_m,
        nsteps=nsteps,
        left_x=left_x,
        left_r=left_r,
        right_x=right_x,
        right_r=right_r,
        line_block="\n".join(line_calls),
        step_x_array="\n".join(step_pos_lines),
        step_r_array="\n".join(step_rad_lines),
        keyway_list="\n".join(keyway_list_lines),
        keyway_calls="\n".join(keyway_call_lines),
        keyway_msg="\n".join(keyway_msg_lines),
    )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, 'w', encoding='ascii') as f:
        f.write(vba)

    print("VBA Macro generated: {}".format(output_path))
    print("Size: {:,} bytes".format(os.path.getsize(output_path)))
    print("Contour lines: {}".format(len(sketch_lines)))
    print("Step fillets: {}".format(nsteps))
    print("Keyways: {}".format(len(KEYWAYS)))


if __name__ == "__main__":
    out = "CAD/CreateShaftMacro.bas"
    if len(sys.argv) > 1:
        out = sys.argv[1]
    generate_vba_module(out)
