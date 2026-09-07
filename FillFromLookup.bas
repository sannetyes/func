Attribute VB_Name = "FillFromLookup"
Option Explicit

' ============================================================
'  For each value in column B, find its match in column F and
'  write the corresponding G value into column I on the same row.
'  By default only empty cells in I are filled.
' ============================================================

' ----------------------- SETTINGS ---------------------------
Private Const SHEET_NAME      As String = ""      ' "" = active sheet
Private Const FIRST_ROW       As Long = 2         ' first data row (2 if there is a header)
Private Const KEY_COL         As String = "B"     ' values to look up
Private Const LOOKUP_COL      As String = "F"     ' column searched for the match
Private Const RESULT_COL      As String = "G"     ' column the value is taken from
Private Const TARGET_COL      As String = "I"     ' column the value is written to
Private Const ONLY_EMPTY      As Boolean = True   ' skip rows where I already has something
Private Const NOT_FOUND_TEXT  As String = ""      ' written when B has no match in F
Private Const CASE_SENSITIVE  As Boolean = False  ' True = HLR_1 and hlr_1 are different
' ------------------------------------------------------------


Public Sub FillFromLookup()

    Dim ws As Worksheet
    Dim lastKeyRow As Long, lastLookupRow As Long
    Dim keys As Variant, lookups As Variant, results As Variant, targets As Variant
    Dim map As Object
    Dim i As Long, k As String
    Dim nFilled As Long, nNotFound As Long, nSkipped As Long, nBlankKey As Long
    Dim oldCalc As XlCalculation

    ' --- resolve the sheet ---
    On Error Resume Next
    If Len(SHEET_NAME) = 0 Then
        Set ws = ActiveSheet
    Else
        Set ws = ThisWorkbook.Worksheets(SHEET_NAME)
    End If
    On Error GoTo 0

    If ws Is Nothing Then
        MsgBox "Sheet not found: " & SHEET_NAME, vbExclamation
        Exit Sub
    End If

    ' --- find the end of each column ---
    lastKeyRow = ws.Cells(ws.Rows.Count, KEY_COL).End(xlUp).Row
    lastLookupRow = ws.Cells(ws.Rows.Count, LOOKUP_COL).End(xlUp).Row

    If lastKeyRow < FIRST_ROW Then
        MsgBox "No data found in column " & KEY_COL & ".", vbExclamation
        Exit Sub
    End If
    If lastLookupRow < FIRST_ROW Then
        MsgBox "No data found in column " & LOOKUP_COL & ".", vbExclamation
        Exit Sub
    End If

    ' --- read everything into memory ---
    keys = ReadCol(ws, KEY_COL, FIRST_ROW, lastKeyRow)
    targets = ReadCol(ws, TARGET_COL, FIRST_ROW, lastKeyRow)
    lookups = ReadCol(ws, LOOKUP_COL, FIRST_ROW, lastLookupRow)
    results = ReadCol(ws, RESULT_COL, FIRST_ROW, lastLookupRow)

    ' --- build the F -> G map (first occurrence wins, like XLOOKUP) ---
    Set map = CreateObject("Scripting.Dictionary")
    For i = 1 To UBound(lookups, 1)
        k = NormKey(lookups(i, 1))
        If Len(k) > 0 Then
            If Not map.Exists(k) Then map.Add k, results(i, 1)
        End If
    Next i

    ' --- speed up ---
    Application.ScreenUpdating = False
    oldCalc = Application.Calculation
    Application.Calculation = xlCalculationManual

    ' --- walk column B ---
    For i = 1 To UBound(keys, 1)

        k = NormKey(keys(i, 1))

        If Len(k) = 0 Then
            nBlankKey = nBlankKey + 1                        ' nothing to look up

        ElseIf ONLY_EMPTY And Len(Trim$(CStr(targets(i, 1)))) > 0 Then
            nSkipped = nSkipped + 1                          ' I already has a value

        ElseIf map.Exists(k) Then
            ws.Cells(FIRST_ROW + i - 1, TARGET_COL).Value = map(k)
            nFilled = nFilled + 1

        Else
            If Len(NOT_FOUND_TEXT) > 0 Then
                ws.Cells(FIRST_ROW + i - 1, TARGET_COL).Value = NOT_FOUND_TEXT
            End If
            nNotFound = nNotFound + 1
        End If

    Next i

    Application.Calculation = oldCalc
    Application.ScreenUpdating = True

    MsgBox "Filled:        " & nFilled & vbCrLf & _
           "Not found:     " & nNotFound & vbCrLf & _
           "Already set:   " & nSkipped & vbCrLf & _
           "Blank key:     " & nBlankKey & vbCrLf & vbCrLf & _
           "Unique keys in " & LOOKUP_COL & ": " & map.Count, _
           vbInformation, "FillFromLookup"

End Sub


' Reads one column into a 2D array, even when the range is a single cell.
Private Function ReadCol(ws As Worksheet, col As String, r1 As Long, r2 As Long) As Variant
    Dim v As Variant, arr() As Variant

    v = ws.Range(ws.Cells(r1, col), ws.Cells(r2, col)).Value

    If Not IsArray(v) Then
        ReDim arr(1 To 1, 1 To 1)
        arr(1, 1) = v
        v = arr
    End If

    ReadCol = v
End Function


' Normalises a cell value so that " HLR_1 " and "HLR_1" match,
' and so that the number 1234 matches the text "1234".
Private Function NormKey(v As Variant) As String
    Dim s As String

    If IsError(v) Then
        NormKey = ""
        Exit Function
    End If

    s = Trim$(CStr(v))
    If Not CASE_SENSITIVE Then s = LCase$(s)

    NormKey = s
End Function
