Attribute VB_Name = "MatchAndPullColumn"
Option Explicit

'=====================================================================
'  MatchAndPullColumn
'  ------------------------------------------------------------------
'  WB1 holds the keys          -> KEY_COL_1
'  WB2 holds a key column      -> KEY_COL_2
'         and a value column   -> VALUE_COL_2
'
'  For every key in WB1 the macro finds that key ANYWHERE in WB2 and
'  writes the matching value into a new column in WB1.
'  The two files do NOT need to be in the same row order.
'
'  Both workbooks must be open when you run this.
'=====================================================================


'------------------------- SETTINGS ----------------------------------
' File names exactly as they appear in the Excel title bar (with extension).

Private Const WB1_NAME        As String = "Book1.xlsx"    ' the file that gets the new column
Private Const WB1_SHEET       As String = "Sheet1"
Private Const KEY_COL_1       As String = "A"             ' column1: keys to look up
Private Const OUT_COL_1       As String = "B"             ' where the result is written
Private Const OUT_HEADER      As String = "Matched value"

Private Const WB2_NAME        As String = "Book2.xlsx"    ' the lookup file
Private Const WB2_SHEET       As String = "Sheet1"
Private Const KEY_COL_2       As String = "A"             ' column2: keys to match against
Private Const VALUE_COL_2     As String = "C"             ' column3: value to bring over

Private Const FIRST_ROW       As Long = 2                 ' 2 = data starts under a header; use 1 if no header
Private Const INSERT_COLUMN   As Boolean = True           ' True = insert a blank column so nothing is overwritten
Private Const NOT_FOUND_TEXT  As String = ""              ' e.g. "" or "#N/A" or "not found"
Private Const IGNORE_CASE     As Boolean = True           ' treat "ABC" and "abc" as the same key
Private Const TRIM_KEYS       As Boolean = True           ' ignore leading/trailing spaces
'---------------------------------------------------------------------


Public Sub MatchAndPullColumn()

    Dim ws1 As Worksheet, ws2 As Worksheet
    Dim map As Object
    Dim keys1 As Variant, keys2 As Variant, vals2 As Variant
    Dim out() As Variant
    Dim i As Long
    Dim lastRow1 As Long, lastRow2 As Long
    Dim k As String
    Dim hits As Long, misses As Long, dups As Long

    On Error GoTo Fail

    Set ws1 = GetSheet(WB1_NAME, WB1_SHEET)
    Set ws2 = GetSheet(WB2_NAME, WB2_SHEET)

    lastRow1 = ws1.Cells(ws1.Rows.Count, KEY_COL_1).End(xlUp).Row
    lastRow2 = ws2.Cells(ws2.Rows.Count, KEY_COL_2).End(xlUp).Row

    If lastRow1 < FIRST_ROW Or lastRow2 < FIRST_ROW Then
        MsgBox "One of the key columns has no data below row " & FIRST_ROW & ".", vbExclamation
        Exit Sub
    End If

    ' --- read everything into arrays first: this is what makes it fast ---
    keys1 = ReadColumn(ws1, KEY_COL_1, FIRST_ROW, lastRow1)
    keys2 = ReadColumn(ws2, KEY_COL_2, FIRST_ROW, lastRow2)
    vals2 = ReadColumn(ws2, VALUE_COL_2, FIRST_ROW, lastRow2)

    ' --- build the lookup index from WB2 (order-independent) ---
    Set map = CreateObject("Scripting.Dictionary")

    For i = 1 To UBound(keys2, 1)
        k = NormKey(keys2(i, 1))
        If Len(k) > 0 Then
            If map.Exists(k) Then
                dups = dups + 1              ' duplicate key: first occurrence wins
            Else
                map.Add k, vals2(i, 1)
            End If
        End If
    Next i

    ' --- match every WB1 key against the index ---
    ReDim out(1 To UBound(keys1, 1), 1 To 1)

    For i = 1 To UBound(keys1, 1)
        k = NormKey(keys1(i, 1))
        If map.Exists(k) Then
            out(i, 1) = map(k)
            hits = hits + 1
        Else
            out(i, 1) = NOT_FOUND_TEXT
            misses = misses + 1
        End If
    Next i

    ' --- write the new column in one shot ---
    Application.ScreenUpdating = False

    With ws1
        If INSERT_COLUMN Then .Columns(OUT_COL_1).Insert Shift:=xlToRight
        If FIRST_ROW > 1 Then .Cells(FIRST_ROW - 1, OUT_COL_1).Value = OUT_HEADER
        .Range(.Cells(FIRST_ROW, OUT_COL_1), .Cells(lastRow1, OUT_COL_1)).Value = out
        .Columns(OUT_COL_1).EntireColumn.AutoFit
    End With

    Application.ScreenUpdating = True

    MsgBox "Done." & vbCrLf & vbCrLf & _
           "Rows processed : " & UBound(keys1, 1) & vbCrLf & _
           "Matched        : " & hits & vbCrLf & _
           "Not found      : " & misses & vbCrLf & _
           "Duplicate keys in " & WB2_NAME & " : " & dups, _
           vbInformation, "MatchAndPullColumn"
    Exit Sub

Fail:
    Application.ScreenUpdating = True
    MsgBox "Error " & Err.Number & ": " & Err.Description, vbCritical, "MatchAndPullColumn"

End Sub


'--------------------------- helpers ---------------------------------

' Returns a worksheet from an open workbook, with clear errors if either is missing.
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


' Reads a single column into a 1-based 2D array, even when it is only one row tall.
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


' Normalises a cell value so that "  ABC " and "abc" match, and 123 matches "123".
Private Function NormKey(ByVal v As Variant) As String

    Dim s As String

    If IsError(v) Then
        NormKey = ""
        Exit Function
    End If

    If IsEmpty(v) Or IsNull(v) Then
        NormKey = ""
        Exit Function
    End If

    s = CStr(v)
    If TRIM_KEYS Then s = Trim$(s)
    If IGNORE_CASE Then s = LCase$(s)

    NormKey = s

End Function
