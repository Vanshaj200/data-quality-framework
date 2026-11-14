# Resolves a working mysql.exe path. On this machine, plain "mysql" in
# PowerShell resolves to a broken C:\WINDOWS\system32\mysql stub (not the
# real client at D:\bin\mysql.exe) - "Cannot run a document in the middle
# of a pipeline". Dot-source this file to get $MySqlExe, or run it directly
# to print the path it found.
function Find-MySqlExe {
    $cmd = Get-Command mysql -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.CommandType -eq "Application" -and $cmd.Source -match "mysql\.exe$") {
        return $cmd.Source
    }
    $candidates = @(
        "D:\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    throw "Could not find a working mysql.exe. Edit scripts/find_mysql.ps1 and add its path to `$candidates."
}

$MySqlExe = Find-MySqlExe
if ($MyInvocation.InvocationName -ne ".") {
    Write-Host $MySqlExe
}
