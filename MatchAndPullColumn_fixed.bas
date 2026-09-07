Attribute VB_Name = "MatchAndPullColumn"
Option Explicit

'=====================================================================
'  MatchAndPullColumn  -  corrected version
'  ------------------------------------------------------------------
'  Fixes over the previous version:
'    1. Guards against the key column drifting when a column is
'       inserted to its left (broke every run after the first).
'    2. Clears formatting on the inserted column, so it cannot
'       inherit a hidden or date format from its left neighbour.
'    3. NormKey no longer uses CStr on numbers - no scientific
'       notation, no locale decimal separator, no date serials.
'    4. NormKey strips CHR(160), tabs, CR/LF and zero-width
'       characters, which Trim$ leaves in place.
'=====================================================================


'------------------------- SETTINGS ----------------------------------
Private Const WB1_NAME        As String = "Book1.xlsx"
Private Const WB1_SHEET       As String = "Sheet1"
Private Const KEY_COL_1       As String = "A"
Private Const OUT_COL_1       As String = "B"
Private Const OUT_HEADER      As String = "Matched value"

Private Const WB2_NAME        As String = "Book2.xlsx"
Private Const WB2_SHEET       As String = "Sheet1"
Private Const KEY_COL_2       As String = "A"
Private Const VALUE_COL_2     As String = "C"

Private Const FIRST_ROW       As Long = 2
Private Const INSERT_COLUMN   As Boolean = True
Private Const NOT_FOUND_TEXT  As String = ""
Private Const IGNORE_CASE     As Boolean = True
Private Const TRIM_KEYS       As Boolean = True
'---------------------------------------------------------------------


Public Sub MatchAndPullColumn()

    Dim ws1 As Worksheet, ws2 As Worksheet
    Dim map As Object
    Dim keys1 As Variant, keys2 As Variant, vals2 As Variant
    Dim out() As Variant
    Dim i As Long
    Dim lastRow1 As Long, lastRow2 As Long
    Dim keyIdx As Long, outIdx As Long
    Dim k As String
    Dim hits As Long, misses As Long, dups As Long, blanks As Long

    On Error GoTo Fail

    Set ws1 = GetSheet(WB1_NAME, WB1_SHEET)
    Set ws2 = GetSheet(WB2_NAME, WB2_SHEET)

    ' --- FIX 1: refuse to insert left of the key column ---------------
    ' Inserting there shifts KEY_COL_1 one column right, so the next run
    ' would read the wrong column and match nothing.
    keyIdx = ws1.Columns(KEY_COL_1).Column
    outIdx = ws1.Columns(OUT_COL_1).Column

    If INSERT_COLUMN And outIdx <= keyIdx Then
        MsgBox "OUT_COL_1 (" & OUT_COL_1 & ") is at or left of KEY_COL_1 (" & KEY_COL_1 & ")." & vbCrLf & vbCrLf & _
               "Inserting there shifts the key column right, so the next run would " & _
               "read the wrong column." & vbCrLf & vbCrLf & _
               "Either move OUT_COL_1 to the right of the key column, or set " & _
               "INSERT_COLUMN = False.", vbCritical, "Unsafe configuration"
        Exit Sub
    End If

    lastRow1 = ws1.Cells(ws1.Rows.Count, KEY_COL_1).End(xlUp).Row
    lastRow2 = ws2.Cells(ws2.Rows.Count, KEY_COL_2).End(xlUp).Row

    If lastRow1 < FIRST_ROW Or lastRow2 < FIRST_ROW Then
        MsgBox "One of the key columns has no data below row " & FIRST_ROW & ".", vbExclamation
        Exit Sub
    End If

    keys1 = ReadColumn(ws1, KEY_COL_1, FIRST_ROW, lastRow1)
    keys2 = ReadColumn(ws2, KEY_COL_2, FIRST_ROW, lastRow2)
    vals2 = ReadColumn(ws2, VALUE_COL_2, FIRST_ROW, lastRow2)

    Set map = CreateObject("Scripting.Dictionary")

    For i = 1 To UBound(keys2, 1)
        k = NormKey(keys2(i, 1))
        If Len(k) > 0 Then
            If map.Exists(k) Then
                dups = dups + 1
            Else
                map.Add k, vals2(i, 1)
            End If
        End If
    Next i

    ReDim out(1 To UBound(keys1, 1), 1 To 1)

    For i = 1 To UBound(keys1, 1)
        k = NormKey(keys1(i, 1))
        If map.Exists(k) Then
            out(i, 1) = map(k)
            hits = hits + 1
            ' a hit on an empty source cell looks identical to a miss on the sheet
            If IsEmpty(map(k)) Or CStr(map(k)) = "" Then blanks = blanks + 1
        Else
            out(i, 1) = NOT_FOUND_TEXT
            misses = misses + 1
        End If
    Next i

    Application.ScreenUpdating = False

    With ws1
        If INSERT_COLUMN Then
            .Columns(OUT_COL_1).Insert Shift:=xlToRight
            ' --- FIX 2: an inserted column inherits the format of the
            ' column to its left. A ";;;" format would render every
            ' result invisible; a date format would show 1900 dates.
            .Columns(OUT_COL_1).ClearFormats
            .Columns(OUT_COL_1).NumberFormat = "General"
        End If

        If FIRST_ROW > 1 Then .Cells(FIRST_ROW - 1, OUT_COL_1).Value = OUT_HEADER
        .Range(.Cells(FIRST_ROW, OUT_COL_1), .Cells(lastRow1, OUT_COL_1)).Value = out
        .Columns(OUT_COL_1).AutoFit
    End With

    Application.ScreenUpdating = True

    MsgBox "Done." & vbCrLf & vbCrLf & _
           "Rows processed        : " & UBound(keys1, 1) & vbCrLf & _
           "Matched               : " & hits & vbCrLf & _
           "  of which blank source: " & blanks & vbCrLf & _
           "Not found             : " & misses & vbCrLf & _
           "Duplicate keys in WB2 : " & dups & vbCrLf & vbCrLf & _
           "Result written to column " & OUT_COL_1 & ".", _
           vbInformation, "MatchAndPullColumn"
    Exit Sub

Fail:
    Application.ScreenUpdating = True
    MsgBox "Error " & Err.Number & ": " & Err.Description, vbCritical, "MatchAndPullColumn"

End Sub


'--------------------------- helpers ---------------------------------

Private Function GetSheet(ByVal wbName As String, ByVal shName As String) As Worksheet

    Dim wb As Workbook

    On Error Resume Next
    Set wb = Workbooks(wbName)
    On Error GoTo 0

    If wb Is Nothing Then
        Err.Raise vbObjectError + 513, , _
            "Workbook '" & wbName & "' is not open. Open it first, and check the name " & _
            "matches exactly (including the file extension)."
    End If

    On Error Resume Next
    Set GetSheet = wb.Worksheets(shName)
    On Error GoTo 0

    If GetSheet Is Nothing Then
        Err.Raise vbObjectError + 514, , _
            "Sheet '" & shName & "' was not found in '" & wbName & "'."
    End If

End Function


Private Function ReadColumn(ByVal ws As Worksheet, ByVal col As String, _
                            ByVal r1 As Long, ByVal r2 As Long) As Variant

    Dim v As Variant, a() As Variant

    v = ws.Range(ws.Cells(r1, col), ws.Cells(r2, col)).Value

    If IsArray(v) Then
        ReadColumn = v
    Else
        ReDim a(1 To 1, 1 To 1)
        a(1, 1) = v
        ReadColumn = a
    End If

End Function


' --- FIX 3 and 4 -----------------------------------------------------
' Builds a comparison key that is stable across storage types and free
' of the invisible characters Trim$ leaves behind.
Private Function NormKey(ByVal v As Variant) As String

    Dim s As String, buf As String
    Dim j As Long, ch As Long

    If IsError(v) Then NormKey = "": Exit Function
    If IsEmpty(v) Then NormKey = "": Exit Function
    If IsNull(v) Then NormKey = "": Exit Function

    Select Case VarType(v)

        Case vbDouble, vbSingle, vbInteger, vbLong, vbCurrency, vbDecimal
            ' Format$ with an explicit picture avoids CStr's scientific
            ' notation on long IDs and its locale decimal separator.
            If v = Int(v) Then
                s = Format$(v, "0")
            Else
                s = Format$(v, "0.##############")
                s = Replace$(s, ",", ".")
            End If

        Case vbDate
            s = Format$(v, "yyyy-mm-dd")

        Case vbBoolean
            s = IIf(v, "TRUE", "FALSE")

        Case Else
            s = CStr(v)

    End Select

    ' Non-breaking space becomes a normal space; tabs, line breaks and
    ' zero-width characters are dropped entirely.
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

    s = buf

    If TRIM_KEYS Then s = Trim$(s)
    If IGNORE_CASE Then s = LCase$(s)

    NormKey = s

End Function
