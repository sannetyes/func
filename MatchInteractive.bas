Sub MatchFtoC()
    Dim ws As Worksheet, d As Object
    Dim lastC As Long, lastF As Long, i As Long
    Dim c As Variant, f As Variant, g As Variant, out() As Variant
    Dim k As String, hits As Long

    Set ws = ActiveSheet
    lastC = ws.Cells(ws.Rows.Count, "C").End(xlUp).Row
    lastF = ws.Cells(ws.Rows.Count, "F").End(xlUp).Row

    c = ws.Range("C2:C" & lastC).Value
    f = ws.Range("F2:F" & lastF).Value
    g = ws.Range("G2:G" & lastF).Value

    Set d = CreateObject("Scripting.Dictionary")
    For i = 1 To UBound(f, 1)
        k = Norm(f(i, 1))
        If Len(k) > 0 Then If Not d.Exists(k) Then d.Add k, g(i, 1)
    Next i

    ReDim out(1 To UBound(c, 1), 1 To 1)
    For i = 1 To UBound(c, 1)
        k = Norm(c(i, 1))
        If d.Exists(k) Then
            out(i, 1) = d(k)
            hits = hits + 1
        Else
            out(i, 1) = ""
        End If
    Next i

    ws.Range("H2:H" & lastC).Value = out
    MsgBox hits & " of " & UBound(c, 1) & " matched."
End Sub

Private Function Norm(ByVal v As Variant) As String
    Dim s As String
    If IsError(v) Or IsEmpty(v) Then Exit Function
    If IsNumeric(v) And Not VarType(v) = vbString Then
        s = Format$(v, "0.##############")
    Else
        s = CStr(v)
    End If
    s = Replace$(s, " ", "")           ' normal spaces
    s = Replace$(s, ChrW$(160), "")    ' non-breaking spaces
    s = Replace$(s, vbTab, "")
    s = Replace$(s, vbLf, "")
    s = Replace$(s, vbCr, "")
    Norm = LCase$(s)
End Function
