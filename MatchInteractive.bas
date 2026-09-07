Attribute VB_Name = "MatchInteractive"
Option Explicit

'=====================================================================
'  MatchInteractive
'  ------------------------------------------------------------------
'  No constants to configure. You select each range with the mouse,
'  so there is no way to point it at the wrong sheet or column.
'
'  You can switch between open workbooks while an input box is
'  showing - click the other workbook in the taskbar or via the
'  View > Switch Windows menu, then drag over the range.
'
'  When it finishes it reports what matched, and shows the first
'  few keys that did NOT match together with the closest thing it
'  found on the other side.
'=====================================================================

Public Sub MatchInteractive()

    Dim rKey1 As Range, rKey2 As Range, rVal2 As Range, rOut As Range
    Dim map As Object
    Dim k As String
    Dim i As Long
    Dim hits As Long, misses As Long, dups As Long, blanks As Long
    Dim out() As Variant
    Dim sampleMiss As String, sampleCount As Long
    Dim sampleWB2 As String

    On Error GoTo Fail

    ' ---------------- step 1 ----------------
    Set rKey1 = Application.InputBox( _
        "STEP 1 of 4" & vbCrLf & vbCrLf & _
        "Select the KEY cells in the workbook that should RECEIVE the new column." & vbCrLf & _
        "Data rows only - do not include the header.", _
        "Keys to look up", Type:=8)
    If rKey1 Is Nothing Then Exit Sub
    Set rKey1 = rKey1.Columns(1)

    ' ---------------- step 2 ----------------
    Set rKey2 = Application.InputBox( _
        "STEP 2 of 4" & vbCrLf & vbCrLf & _
        "Select the KEY cells in the LOOKUP workbook - the column that should " & _
        "contain the same identifiers." & vbCrLf & _
        "Data rows only.", _
        "Keys to match against", Type:=8)
    If rKey2 Is Nothing Then Exit Sub
    Set rKey2 = rKey2.Columns(1)

    ' ---------------- step 3 ----------------
    Set rVal2 = Application.InputBox( _
        "STEP 3 of 4" & vbCrLf & vbCrLf & _
        "Select the VALUE cells in the LOOKUP workbook - the column you want " & _
        "brought across." & vbCrLf & _
        "Must be the same number of rows as step 2.", _
        "Values to copy", Type:=8)
    If rVal2 Is Nothing Then Exit Sub
    Set rVal2 = rVal2.Columns(1)

    If rVal2.Rows.Count <> rKey2.Rows.Count Then
        MsgBox "Step 2 covered " & rKey2.Rows.Count & " rows but step 3 covered " & _
               rVal2.Rows.Count & "." & vbCrLf & vbCrLf & _
               "They must line up row for row.", vbCritical
        Exit Sub
    End If

    ' ---------------- step 4 ----------------
    Set rOut = Application.InputBox( _
        "STEP 4 of 4" & vbCrLf & vbCrLf & _
        "Click the SINGLE cell where the results should start." & vbCrLf & _
        "This should be in the same workbook and on the same row as the first " & _
        "cell you selected in step 1." & vbCrLf & vbCrLf & _
        "Anything already there will be overwritten.", _
        "Where to write", Type:=8)
    If rOut Is Nothing Then Exit Sub
    Set rOut = rOut.Cells(1, 1)

    ' ---------------- build the index ----------------
    Set map = CreateObject("Scripting.Dictionary")

    For i = 1 To rKey2.Rows.Count
        k = NormKey(rKey2.Cells(i, 1).Value)
        If Len(k) > 0 Then
            If map.Exists(k) Then
                dups = dups + 1
            Else
                map.Add k, rVal2.Cells(i, 1).Value
            End If
        End If
        If i <= 3 Then sampleWB2 = sampleWB2 & "   [" & k & "]" & vbCrLf
    Next i

    ' ---------------- match ----------------
    ReDim out(1 To rKey1.Rows.Count, 1 To 1)

    For i = 1 To rKey1.Rows.Count
        k = NormKey(rKey1.Cells(i, 1).Value)

        If map.Exists(k) Then
            out(i, 1) = map(k)
            hits = hits + 1
            If Len(CStr(map(k))) = 0 Then blanks = blanks + 1
        Else
            out(i, 1) = ""
            misses = misses + 1
            If sampleCount < 3 And Len(k) > 0 Then
                sampleMiss = sampleMiss & "   [" & k & "]" & vbCrLf
                sampleCount = sampleCount + 1
            End If
        End If
    Next i

    ' ---------------- write ----------------
    Application.ScreenUpdating = False
    With rOut.Resize(rKey1.Rows.Count, 1)
        .ClearFormats
        .NumberFormat = "General"
        .Value = out
        .EntireColumn.AutoFit
    End With
    Application.ScreenUpdating = True

    ' ---------------- report ----------------
    MsgBox "Looked up : " & rKey1.Address(External:=True) & vbCrLf & _
           "Against   : " & rKey2.Address(External:=True) & vbCrLf & _
           "Pulled    : " & rVal2.Address(External:=True) & vbCrLf & _
           "Written   : " & rOut.Address(External:=True) & vbCrLf & _
           String$(46, "-") & vbCrLf & _
           "Matched              : " & hits & vbCrLf & _
           "  of which blank      : " & blanks & vbCrLf & _
           "Not found            : " & misses & vbCrLf & _
           "Duplicate lookup keys : " & dups & vbCrLf & vbCrLf & _
           "First keys as read from the lookup file:" & vbCrLf & sampleWB2 & vbCrLf & _
           IIf(misses > 0, "First keys that found no match:" & vbCrLf & sampleMiss, ""), _
           vbInformation, "MatchInteractive"
    Exit Sub

Fail:
    Application.ScreenUpdating = True
    MsgBox "Error " & Err.Number & ": " & Err.Description, vbCritical

End Sub


Private Function NormKey(ByVal v As Variant) As String

    Dim s As String, buf As String
    Dim j As Long, ch As Long

    If IsError(v) Then NormKey = "": Exit Function
    If IsEmpty(v) Then NormKey = "": Exit Function
    If IsNull(v) Then NormKey = "": Exit Function

    Select Case VarType(v)
        Case vbDouble, vbSingle, vbInteger, vbLong, vbCurrency, vbDecimal
            If v = Int(v) Then
                s = Format$(v, "0")
            Else
                s = Replace$(Format$(v, "0.##############"), ",", ".")
            End If
        Case vbDate
            s = Format$(v, "yyyy-mm-dd")
        Case vbBoolean
            s = IIf(v, "TRUE", "FALSE")
        Case Else
            s = CStr(v)
    End Select

    For j = 1 To Len(s)
        ch = AscW(Mid$(s, j, 1))
        Select Case ch
            Case 160
                buf = buf & " "
            Case 9, 10, 13, 8203, 8204, 8205, 65279
                ' drop
            Case Else
                buf = buf & ChrW$(ch)
        End Select
    Next j

    NormKey = LCase$(Trim$(buf))

End Function
