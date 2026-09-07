Attribute VB_Name = "HlrLinkFiller"
Option Explicit

'==============================================================================
'  HlrLinkFiller
'  --------------------------------------------------------------------------
'  wb1 : python_func_list   / sheet "Fonksiyonlar_new"
'          col B = Class/File Name
'          col C = Function Name
'          col F = HLR Ids          <-- filled by this macro
'
'  wb2 : sci_5_5_links      / sheet "Sheet1"
'          col A = Function Name
'          col B = Links
'
'  wb3 : sci_6_7_links      / sheet "sci_6-7_outlinks_export"
'          col B = Class/Function
'          col C = Links
'
'  LOGIC
'    1) For every wb1 row, match Function Name (col C) against wb2 col A.
'       On a hit, write wb2 col B (Links) into wb1 col F.
'    2) Only for rows whose col F is STILL empty, match Class/File Name (col B)
'       against wb3 col B.  On a hit, write wb3 col C (Links) into col F.
'    3) Rows that match nothing are left empty and listed on the log sheet.
'
'  MATCHING
'    * Row order is irrelevant - both source sheets are loaded into hash
'      dictionaries, so nothing has to be sorted.
'    * ALL whitespace is removed before comparing:
'          "Motor :: start"  ==  "Motor::start"  ==  " Motor::start "
'      (normal space, tab, CR, LF and non-breaking space CHR(160)).
'    * Comparison is case-insensitive while IGNORE_CASE = True.
'    * If the same key appears several times in wb2/wb3, every distinct link
'      is collected and joined with JOIN_SEPARATOR ->  "HLR_1, HLR_2"
'
'  USAGE
'    ALT+F11  ->  File / Import File...  ->  HlrLinkFiller.bas
'    Open the three workbooks (or put them next to the macro workbook), then
'    run  FillHlrIds.   Run  Test_FillHlrIds  first to verify the logic.
'==============================================================================


'============================== SETTINGS ======================================

' Workbook file names WITHOUT extension. Matching ignores case and any
' non-alphanumeric character, so "sci_5_5_links" also finds "sci-5-5 links".
Private Const WB1_BASENAME As String = "python_func_list"
Private Const WB2_BASENAME As String = "sci_5_5_links"
Private Const WB3_BASENAME As String = "sci_6_7_links"

' Sheet names (also matched ignoring case / punctuation)
Private Const WB1_SHEET As String = "Fonksiyonlar_new"
Private Const WB2_SHEET As String = "Sheet1"
Private Const WB3_SHEET As String = "sci_6-7_outlinks_export"

' Column numbers  (A=1, B=2, C=3, D=4, E=5, F=6 ...)
Private Const WB1_COL_CLASS As Long = 2      ' B  Class/File Name
Private Const WB1_COL_FUNC  As Long = 3      ' C  Function Name
Private Const WB1_COL_HLR   As Long = 6      ' F  HLR Ids   (target)
Private Const WB1_FIRST_ROW As Long = 2      ' first data row (1 = header)

Private Const WB2_COL_FUNC As Long = 1       ' A  Function Name
Private Const WB2_COL_LINK As Long = 2       ' B  Links
Private Const WB2_FIRST_ROW As Long = 2

Private Const WB3_COL_CLASS As Long = 2      ' B  Class/Function
Private Const WB3_COL_LINK  As Long = 3      ' C  Links
Private Const WB3_FIRST_ROW As Long = 2

' Behaviour
Private Const IGNORE_CASE As Boolean = True        ' case-insensitive matching
Private Const OVERWRITE_EXISTING As Boolean = False ' False = never touch a cell
                                                    ' in col F that already has
                                                    ' a value (safe re-runs)
Private Const JOIN_SEPARATOR As String = ", "      ' between multiple links
Private Const HIGHLIGHT_RESULTS As Boolean = True  ' colour the filled cells
Private Const WRITE_LOG_SHEET As Boolean = True    ' unmatched rows report
Private Const LOG_SHEET_NAME As String = "HLR_Link_Log"

' Fill colours (BGR)
Private Const CLR_FUNC_HIT  As Long = &HD8F0D8     ' light green  - wb2 hit
Private Const CLR_CLASS_HIT As Long = &HB0E8FF     ' light amber  - wb3 hit
Private Const CLR_NO_HIT    As Long = &HD0D0FF     ' light red    - no match

'==============================================================================

Private mFolderOverride As String        ' used by the test harness


'------------------------------------------------------------------------------
' Entry point
'------------------------------------------------------------------------------
Public Sub FillHlrIds()
    Dim report As String
    On Error GoTo Fail
    report = FillHlrIdsCore(WRITE_LOG_SHEET)
    MsgBox report, vbInformation, "HLR Ids"
    Exit Sub
Fail:
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    MsgBox "ERROR " & Err.Number & vbCrLf & Err.Description, vbCritical, "HLR Ids"
End Sub


'------------------------------------------------------------------------------
' Core routine - returns a short text report (no message boxes, so the test
' harness can call it too)
'------------------------------------------------------------------------------
Public Function FillHlrIdsCore(ByVal writeLog As Boolean) As String

    Dim wb1 As Workbook, wb2 As Workbook, wb3 As Workbook
    Dim ws1 As Worksheet, ws2 As Worksheet, ws3 As Worksheet
    Dim dFunc As Object, dClass As Object
    Dim nFunc As Long, nClass As Long
    Dim scrn As Boolean, calcMode As XlCalculation

    Set wb1 = GetWorkbookByBaseName(WB1_BASENAME)
    Set wb2 = GetWorkbookByBaseName(WB2_BASENAME)
    Set wb3 = GetWorkbookByBaseName(WB3_BASENAME)

    Set ws1 = GetSheet(wb1, WB1_SHEET)
    Set ws2 = GetSheet(wb2, WB2_SHEET)
    Set ws3 = GetSheet(wb3, WB3_SHEET)

    scrn = Application.ScreenUpdating
    calcMode = Application.Calculation
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual

    On Error GoTo CleanUp

    ' --- source lookups -------------------------------------------------
    Set dFunc = BuildLookup(ws2, WB2_COL_FUNC, WB2_COL_LINK, WB2_FIRST_ROW, nFunc)
    Set dClass = BuildLookup(ws3, WB3_COL_CLASS, WB3_COL_LINK, WB3_FIRST_ROW, nClass)

    ' --- read target sheet in one shot ----------------------------------
    Dim lastRow As Long, maxCol As Long
    maxCol = WB1_COL_HLR
    If WB1_COL_CLASS > maxCol Then maxCol = WB1_COL_CLASS
    If WB1_COL_FUNC > maxCol Then maxCol = WB1_COL_FUNC

    lastRow = LastDataRow(ws1, WB1_COL_CLASS)
    If LastDataRow(ws1, WB1_COL_FUNC) > lastRow Then lastRow = LastDataRow(ws1, WB1_COL_FUNC)

    If lastRow < WB1_FIRST_ROW Then
        FillHlrIdsCore = "'" & ws1.Name & "' has no data rows."
        GoTo CleanUp
    End If

    Dim src As Variant
    src = ws1.Range(ws1.Cells(WB1_FIRST_ROW, 1), ws1.Cells(lastRow, maxCol)).Value

    Dim nRows As Long
    nRows = UBound(src, 1)

    Dim outv() As Variant
    ReDim outv(1 To nRows, 1 To 1)

    Dim hitFunc As Long, hitClass As Long, missed As Long
    Dim kept As Long, blankRows As Long
    Dim missLog() As Variant, nMiss As Long
    ReDim missLog(1 To nRows, 1 To 4)

    Dim tagFunc() As Boolean, tagClass() As Boolean, tagMiss() As Boolean
    ReDim tagFunc(1 To nRows)
    ReDim tagClass(1 To nRows)
    ReDim tagMiss(1 To nRows)

    Dim i As Long, fKey As String, cKey As String, cur As String

    For i = 1 To nRows
        cur = CellText(src(i, WB1_COL_HLR))
        fKey = NormKey(src(i, WB1_COL_FUNC))
        cKey = NormKey(src(i, WB1_COL_CLASS))

        outv(i, 1) = src(i, WB1_COL_HLR)          ' default: leave as is

        If Len(fKey) = 0 And Len(cKey) = 0 Then
            blankRows = blankRows + 1              ' completely empty row

        ElseIf Len(cur) > 0 And Not OVERWRITE_EXISTING Then
            kept = kept + 1                        ' already filled -> untouched

        ElseIf Len(fKey) > 0 And dFunc.Exists(fKey) Then
            outv(i, 1) = SafeText(dFunc(fKey))     ' 1) function match  (wb2)
            hitFunc = hitFunc + 1
            tagFunc(i) = True

        ElseIf Len(cKey) > 0 And dClass.Exists(cKey) Then
            outv(i, 1) = SafeText(dClass(cKey))    ' 2) class match     (wb3)
            hitClass = hitClass + 1
            tagClass(i) = True

        Else
            missed = missed + 1                    ' 3) nothing found
            tagMiss(i) = True
            nMiss = nMiss + 1
            missLog(nMiss, 1) = WB1_FIRST_ROW + i - 1
            missLog(nMiss, 2) = CellText(src(i, WB1_COL_CLASS))
            missLog(nMiss, 3) = CellText(src(i, WB1_COL_FUNC))
            missLog(nMiss, 4) = "no match in " & WB2_BASENAME & " / " & WB3_BASENAME
        End If
    Next i

    ' --- write column F back in one shot --------------------------------
    ws1.Range(ws1.Cells(WB1_FIRST_ROW, WB1_COL_HLR), _
              ws1.Cells(lastRow, WB1_COL_HLR)).Value = outv

    ' --- colour code -----------------------------------------------------
    If HIGHLIGHT_RESULTS Then
        For i = 1 To nRows
            If tagFunc(i) Then
                ws1.Cells(WB1_FIRST_ROW + i - 1, WB1_COL_HLR).Interior.Color = CLR_FUNC_HIT
            ElseIf tagClass(i) Then
                ws1.Cells(WB1_FIRST_ROW + i - 1, WB1_COL_HLR).Interior.Color = CLR_CLASS_HIT
            ElseIf tagMiss(i) Then
                ws1.Cells(WB1_FIRST_ROW + i - 1, WB1_COL_HLR).Interior.Color = CLR_NO_HIT
            End If
        Next i
    End If

    ' --- log sheet -------------------------------------------------------
    If writeLog Then WriteLog wb1, missLog, nMiss

    FillHlrIdsCore = _
        "Source keys : " & nFunc & " function names (" & WB2_BASENAME & "), " & _
        nClass & " class names (" & WB3_BASENAME & ")" & vbCrLf & vbCrLf & _
        "Rows processed        : " & nRows & vbCrLf & _
        "Filled from function  : " & hitFunc & vbCrLf & _
        "Filled from class     : " & hitClass & vbCrLf & _
        "No match (left empty) : " & missed & vbCrLf & _
        "Already filled (kept) : " & kept & vbCrLf & _
        "Empty rows skipped    : " & blankRows

CleanUp:
    Dim savedErr As Long, savedDesc As String
    savedErr = Err.Number
    savedDesc = Err.Description
    Application.Calculation = calcMode
    Application.ScreenUpdating = scrn
    If savedErr <> 0 Then Err.Raise savedErr, "FillHlrIdsCore", savedDesc
End Function


'==============================================================================
' Helpers
'==============================================================================

'--- remove every kind of whitespace, optionally lower-case -------------------
Private Function NormKey(ByVal v As Variant) As String
    Dim s As String
    If IsError(v) Then
        NormKey = ""
        Exit Function
    End If
    s = CStr(v & "")
    If Len(s) = 0 Then
        NormKey = ""
        Exit Function
    End If
    s = Replace$(s, " ", "")
    s = Replace$(s, vbTab, "")
    s = Replace$(s, vbCr, "")
    s = Replace$(s, vbLf, "")
    s = Replace$(s, ChrW$(160), "")     ' non-breaking space
    If IGNORE_CASE Then s = LCase$(s)
    NormKey = s
End Function

'--- normalise a workbook / sheet name (ignore case and punctuation) ---------
Private Function NormName(ByVal s As String) As String
    Dim i As Long, ch As String, out As String
    s = LCase$(s)
    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        If (ch >= "a" And ch <= "z") Or (ch >= "0" And ch <= "9") Then out = out & ch
    Next i
    NormName = out
End Function

Private Function CellText(ByVal v As Variant) As String
    If IsError(v) Then
        CellText = ""
    Else
        CellText = Trim$(CStr(v & ""))
    End If
End Function

'--- stop a link that starts with "=" from becoming a formula ----------------
Private Function SafeText(ByVal s As String) As String
    If Left$(s, 1) = "=" Then
        SafeText = "'" & s
    Else
        SafeText = s
    End If
End Function

Private Function LastDataRow(ws As Worksheet, ByVal col As Long) As Long
    LastDataRow = ws.Cells(ws.Rows.Count, col).End(xlUp).Row
End Function

'--- key -> joined links dictionary ------------------------------------------
Private Function BuildLookup(ws As Worksheet, ByVal keyCol As Long, _
                             ByVal valCol As Long, ByVal firstRow As Long, _
                             ByRef keyCount As Long) As Object

    Dim d As Object, seen As Object
    Set d = CreateObject("Scripting.Dictionary")
    Set seen = CreateObject("Scripting.Dictionary")
    keyCount = 0

    Dim maxCol As Long, lastRow As Long
    maxCol = keyCol
    If valCol > maxCol Then maxCol = valCol

    lastRow = LastDataRow(ws, keyCol)
    If LastDataRow(ws, valCol) > lastRow Then lastRow = LastDataRow(ws, valCol)
    If lastRow < firstRow Then
        Set BuildLookup = d
        Exit Function
    End If

    Dim v As Variant
    v = ws.Range(ws.Cells(firstRow, 1), ws.Cells(lastRow, maxCol)).Value

    Dim i As Long, k As String, val As String, dupKey As String
    For i = 1 To UBound(v, 1)
        k = NormKey(v(i, keyCol))
        val = CellText(v(i, valCol))
        If Len(k) > 0 And Len(val) > 0 Then
            dupKey = k & ChrW$(1) & NormKey(val)
            If Not seen.Exists(dupKey) Then
                seen(dupKey) = True
                If d.Exists(k) Then
                    d(k) = d(k) & JOIN_SEPARATOR & val     ' several links / key
                Else
                    d(k) = val
                    keyCount = keyCount + 1
                End If
            End If
        End If
    Next i

    Set BuildLookup = d
End Function

'--- find an open workbook, or open it from disk ------------------------------
Private Function GetWorkbookByBaseName(ByVal baseName As String) As Workbook
    Dim wb As Workbook, nm As String

    For Each wb In Application.Workbooks
        nm = wb.Name
        If InStrRev(nm, ".") > 1 Then nm = Left$(nm, InStrRev(nm, ".") - 1)
        If NormName(nm) = NormName(baseName) Then
            Set GetWorkbookByBaseName = wb
            Exit Function
        End If
    Next wb

    Dim folder As String, exts As Variant, i As Long, p As String
    folder = DataFolder()
    If Len(folder) > 0 Then
        If Right$(folder, 1) <> Application.PathSeparator Then
            folder = folder & Application.PathSeparator
        End If
        exts = Array(".xlsx", ".xlsm", ".xlsb", ".xls")
        For i = LBound(exts) To UBound(exts)
            p = folder & baseName & exts(i)
            If Len(Dir$(p)) > 0 Then
                Set GetWorkbookByBaseName = Workbooks.Open(p)
                Exit Function
            End If
        Next i
    End If

    Err.Raise vbObjectError + 513, "GetWorkbookByBaseName", _
        "Workbook '" & baseName & "' is not open and was not found in:" & vbCrLf & folder
End Function

Private Function GetSheet(wb As Workbook, ByVal sheetName As String) As Worksheet
    Dim ws As Worksheet
    For Each ws In wb.Worksheets
        If NormName(ws.Name) = NormName(sheetName) Then
            Set GetSheet = ws
            Exit Function
        End If
    Next ws
    Err.Raise vbObjectError + 514, "GetSheet", _
        "Sheet '" & sheetName & "' not found in '" & wb.Name & "'."
End Function

Private Function DataFolder() As String
    If Len(mFolderOverride) > 0 Then
        DataFolder = mFolderOverride
    ElseIf Len(ThisWorkbook.Path) > 0 Then
        DataFolder = ThisWorkbook.Path
    Else
        DataFolder = CurDir$
    End If
End Function

Private Sub WriteLog(wb As Workbook, ByRef missLog As Variant, ByVal nMiss As Long)
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = wb.Worksheets(LOG_SHEET_NAME)
    On Error GoTo 0

    If ws Is Nothing Then
        Set ws = wb.Worksheets.Add(After:=wb.Worksheets(wb.Worksheets.Count))
        ws.Name = LOG_SHEET_NAME
    End If

    ws.Cells.Clear
    ws.Range("A1:D1").Value = Array("Row", "Class/File Name", "Function Name", "Reason")
    ws.Range("A1:D1").Font.Bold = True

    If nMiss > 0 Then
        Dim outv() As Variant, i As Long, j As Long
        ReDim outv(1 To nMiss, 1 To 4)
        For i = 1 To nMiss
            For j = 1 To 4
                outv(i, j) = missLog(i, j)
            Next j
        Next i
        ws.Range("A2").Resize(nMiss, 4).Value = outv
    Else
        ws.Range("A2").Value = "All rows matched."
    End If
    ws.Columns("A:D").AutoFit
End Sub


'==============================================================================
'  SELF TEST
'  Builds three throw-away workbooks in the TEMP folder, runs the real macro
'  on them and checks column F cell by cell.  Nothing of yours is touched.
'  Run it, then read the message box / the Immediate window (CTRL+G).
'==============================================================================
Public Sub Test_FillHlrIds()

    Dim tmp As String
    Dim wb1 As Workbook, wb2 As Workbook, wb3 As Workbook
    Dim ws1 As Worksheet
    Dim expected As Variant, labels As Variant
    Dim i As Long, pass As Long, fail As Long
    Dim got As String, msg As String
    Dim prevAlerts As Boolean

    tmp = Environ$("TEMP")
    If Right$(tmp, 1) <> Application.PathSeparator Then tmp = tmp & Application.PathSeparator

    prevAlerts = Application.DisplayAlerts
    Application.DisplayAlerts = False
    Application.ScreenUpdating = False
    On Error GoTo Fail

    '--------------------------------------------------- wb2 : sci_5_5_links
    Set wb2 = Workbooks.Add(xlWBATWorksheet)
    With wb2.Worksheets(1)
        .Name = "Sheet1"
        .Range("A1:B1").Value = Array("Function Name", "Links")
        .Range("A2").Value = "Only::InTwo":   .Range("B2").Value = "HLR_D_1"
        .Range("A3").Value = "Motor::start":  .Range("B3").Value = "HLR_A_1"
        .Range("A4").Value = " calc Sum ":    .Range("B4").Value = "HLR_B_1"
        .Range("A5").Value = "Motor::start":  .Range("B5").Value = "HLR_A_2"
        .Range("A6").Value = "DRIVER::Stop":  .Range("B6").Value = "HLR_C_1"
    End With
    wb2.SaveAs tmp & WB2_BASENAME & ".xlsx", xlOpenXMLWorkbook

    '--------------------------------------------------- wb3 : sci_6_7_links
    Set wb3 = Workbooks.Add(xlWBATWorksheet)
    With wb3.Worksheets(1)
        .Name = "sci_6-7_outlinks_export"
        .Range("A1:C1").Value = Array("No", "Class/Function", "Links")
        .Range("B2").Value = "Gearbox.cpp":  .Range("C2").Value = "HLR_F_1"
        .Range("B3").Value = "Engine.cpp":   .Range("C3").Value = "HLR_E_1"
        .Range("B4").Value = "Motor.cpp":    .Range("C4").Value = "HLR_G_1"
        .Range("B5").Value = "engine.cpp":   .Range("C5").Value = "HLR_E_2"
    End With
    wb3.SaveAs tmp & WB3_BASENAME & ".xlsx", xlOpenXMLWorkbook

    '--------------------------------------------------- wb1 : python_func_list
    Set wb1 = Workbooks.Add(xlWBATWorksheet)
    Set ws1 = wb1.Worksheets(1)
    With ws1
        .Name = "Fonksiyonlar_new"
        .Range("A1:F1").Value = Array("No", "Class/File Name", "Function Name", _
                                      "x", "y", "HLR Ids")
        ' row 2 : function hit, spaces must be ignored, two links joined
        .Range("B2").Value = "Motor.cpp":   .Range("C2").Value = "Motor :: start"
        ' row 3 : no function hit -> class hit (two links joined, case ignored)
        .Range("B3").Value = "Engine.cpp":  .Range("C3").Value = "Engine::run"
        ' row 4 : function hit, source key had leading/inner/trailing spaces
        .Range("B4").Value = "Gearbox.cpp": .Range("C4").Value = "calcSum"
        ' row 5 : no hit anywhere -> stays empty, goes to the log
        .Range("B5").Value = "Unknown.cpp": .Range("C5").Value = "noWhere"
        ' row 6 : col F already filled -> must be preserved untouched
        .Range("B6").Value = "Engine.cpp":  .Range("C6").Value = "Engine::stop"
        .Range("F6").Value = "EXISTING_HLR"
        ' row 7 : function hit only when case is ignored
        .Range("B7").Value = "Driver.cpp":  .Range("C7").Value = "driver::STOP"
        ' row 8 : no function name at all -> class hit
        .Range("B8").Value = "Gearbox.cpp": .Range("C8").Value = ""
        ' row 9 : function name exists in wb3's class column? no -> class hit
        .Range("B9").Value = "Motor.cpp":   .Range("C9").Value = "Motor::stop"
    End With
    wb1.SaveAs tmp & WB1_BASENAME & ".xlsx", xlOpenXMLWorkbook

    '--------------------------------------------------- run the real macro
    mFolderOverride = tmp
    Dim report As String
    report = FillHlrIdsCore(True)
    mFolderOverride = ""

    '--------------------------------------------------- verify
    labels = Array( _
        "row 2  function hit, spaces ignored, 2 links joined", _
        "row 3  fallback to class, case-insensitive dedupe", _
        "row 4  function hit, source key full of spaces", _
        "row 5  no match anywhere -> empty", _
        "row 6  existing value preserved", _
        "row 7  function hit, case ignored", _
        "row 8  empty function name -> class hit", _
        "row 9  function unknown -> class hit (not the wb2 link)")

    expected = Array( _
        "HLR_A_1, HLR_A_2", _
        "HLR_E_1, HLR_E_2", _
        "HLR_B_1", _
        "", _
        "EXISTING_HLR", _
        "HLR_C_1", _
        "HLR_F_1", _
        "HLR_G_1")

    msg = "TEST RESULTS" & vbCrLf & String$(46, "-") & vbCrLf
    For i = 0 To UBound(expected)
        got = Trim$(CStr(ws1.Cells(2 + i, WB1_COL_HLR).Value & ""))
        If got = CStr(expected(i)) Then
            pass = pass + 1
            msg = msg & "PASS  " & labels(i) & vbCrLf
        Else
            fail = fail + 1
            msg = msg & "FAIL  " & labels(i) & vbCrLf & _
                  "        expected [" & expected(i) & "]  got [" & got & "]" & vbCrLf
        End If
    Next i

    msg = msg & String$(46, "-") & vbCrLf & _
          pass & " passed, " & fail & " failed" & vbCrLf & vbCrLf & report

    Debug.Print msg

    '--------------------------------------------------- clean up
    wb1.Close SaveChanges:=False
    wb2.Close SaveChanges:=False
    wb3.Close SaveChanges:=False
    On Error Resume Next
    Kill tmp & WB1_BASENAME & ".xlsx"
    Kill tmp & WB2_BASENAME & ".xlsx"
    Kill tmp & WB3_BASENAME & ".xlsx"
    On Error GoTo 0

    Application.ScreenUpdating = True
    Application.DisplayAlerts = prevAlerts

    MsgBox msg, IIf(fail = 0, vbInformation, vbExclamation), "Test_FillHlrIds"
    Exit Sub

Fail:
    mFolderOverride = ""
    Application.ScreenUpdating = True
    Application.DisplayAlerts = prevAlerts
    MsgBox "Test aborted: " & Err.Number & " - " & Err.Description, vbCritical
End Sub
