'=====================================================================
'  DiagnoseMatch
'  ------------------------------------------------------------------
'  Paste this at the BOTTOM of the same module as MatchAndPullColumn.
'  It reuses that module's constants, so it must live in the same
'  module - it will not compile in a separate one.
'
'  Run DiagnoseMatch, then press Ctrl+G to read the Immediate window.
'=====================================================================

Public Sub DiagnoseMatch()

    Dim ws1 As Worksheet, ws2 As Worksheet
    Dim i As Long, lastRow1 As Long, lastRow2 As Long
    Dim probe As String, found As Long

    Set ws1 = GetSheet(WB1_NAME, WB1_SHEET)
    Set ws2 = GetSheet(WB2_NAME, WB2_SHEET)

    lastRow1 = ws1.Cells(ws1.Rows.Count, KEY_COL_1).End(xlUp).Row
    lastRow2 = ws2.Cells(ws2.Rows.Count, KEY_COL_2).End(xlUp).Row

    Debug.Print String$(70, "=")
    Debug.Print "WB1 : [" & ws1.Parent.Name & "] sheet [" & ws1.Name & "]"
    Debug.Print "      key column " & KEY_COL_1 & ", rows " & FIRST_ROW & " to " & lastRow1
    Debug.Print String$(70, "-")

    For i = FIRST_ROW To WorksheetFunction.Min(FIRST_ROW + 4, lastRow1)
        Debug.Print "  row " & i & "  " & Describe(ws1.Cells(i, KEY_COL_1).Value)
        Debug.Print "         normalised -> [" & NormKey(ws1.Cells(i, KEY_COL_1).Value) & "]"
    Next i

    Debug.Print String$(70, "=")
    Debug.Print "WB2 : [" & ws2.Parent.Name & "] sheet [" & ws2.Name & "]"
    Debug.Print "      key column " & KEY_COL_2 & ", value column " & VALUE_COL_2
    Debug.Print "      rows " & FIRST_ROW & " to " & lastRow2
    Debug.Print String$(70, "-")

    For i = FIRST_ROW To WorksheetFunction.Min(FIRST_ROW + 4, lastRow2)
        Debug.Print "  row " & i & "  " & Describe(ws2.Cells(i, KEY_COL_2).Value)
        Debug.Print "         normalised -> [" & NormKey(ws2.Cells(i, KEY_COL_2).Value) & "]"
        Debug.Print "         value col   -> " & Describe(ws2.Cells(i, VALUE_COL_2).Value)
    Next i

    ' --- take the first WB1 key and hunt for it anywhere in WB2 ---
    probe = NormKey(ws1.Cells(FIRST_ROW, KEY_COL_1).Value)
    found = 0

    For i = FIRST_ROW To lastRow2
        If NormKey(ws2.Cells(i, KEY_COL_2).Value) = probe Then
            found = found + 1
            If found = 1 Then Debug.Print "  first hit at WB2 row " & i
        End If
    Next i

    Debug.Print String$(70, "=")
    Debug.Print "Probe key from WB1 row " & FIRST_ROW & ": [" & probe & "]"
    Debug.Print "Occurrences found in WB2 key column: " & found
    Debug.Print String$(70, "=")

End Sub


' Dumps a cell's raw text, length, VBA type and the Unicode code point of
' every character - this is what exposes invisible junk.
Private Function Describe(ByVal v As Variant) As String

    Dim s As String, j As Long, codes As String

    If IsError(v) Then
        Describe = "<error value>"
        Exit Function
    End If

    If IsEmpty(v) Then
        Describe = "<empty cell>"
        Exit Function
    End If

    s = CStr(v)

    For j = 1 To Len(s)
        codes = codes & AscW(Mid$(s, j, 1)) & " "
    Next j

    Describe = "[" & s & "]  len=" & Len(s) & _
               "  type=" & TypeName(v) & _
               "  codes= " & codes

End Function
