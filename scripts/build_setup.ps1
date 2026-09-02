<#
.SYNOPSIS
    Filler-Cut Windows kurucusunu (Inno Setup) tek komutla uretir.

.DESCRIPTION
    Repo kokunden calistirin:

        .\scripts\build_setup.ps1 -Surum 1.1.0

    Sirayla: exe build (build_exe.ps1) -> WebView2 bootstrapper indir+dogrula
    -> ISCC derlemesi -> artefakt ozeti.

    Cikti: dist_setup\Filler-Cut-Setup-<surum>.exe

.PARAMETER Surum
    Kurucu adina ve AppVersion'a gecen surum. Verilmezse paketten okunur
    (`fillercut.__version__`). Surum bump Faz 5'in isi — burada YAPILMAZ.

.PARAMETER Iscc
    ISCC.exe yolu. Verilmezse once FILLERCUT_ISCC ortam degiskeni, sonra
    bilinen kurulum konumlari denenir. EZBERDEN tek yol yazilmaz.

.PARAMETER SkipExeBuild
    Exe build'i atlar (mevcut dist\fillercut kullanilir). CI'da iki adimi
    ayirmak isteyen icin.
#>
[CmdletBinding()]
param(
    [string]$Surum,
    [string]$Iscc,
    [switch]$SkipExeBuild
)

$ErrorActionPreference = 'Stop'

function Invoke-Yerel {
    <#
      Yerel (native) exe cagrisi + cikis kodu kontrolu.
      PS 5.1'de EAP='Stop' iken native komutun STDERR'e yazmasi terminating
      NativeCommandError uretir (Faz 3'te olculdu: PyInstaller ilk satirda
      "hata" sayiliyordu; ISCC de ayni sekilde davraniyor).
    #>
    param([string]$Aciklama, [scriptblock]$Komut)
    $eski = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Komut } finally { $ErrorActionPreference = $eski }
    if ($LASTEXITCODE -ne 0) { throw ($Aciklama + ' basarisiz (kod ' + $LASTEXITCODE + ')') }
}

$Kok = Split-Path -Parent $PSScriptRoot
Set-Location $Kok
$Python = Join-Path $Kok '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw ('venv bulunamadi: ' + $Python)
}

if (-not $Surum) {
    $Surum = (& $Python -c "from fillercut import __version__; print(__version__)").Trim()
}
# ISCC'nin VersionInfoVersion alani SAYISAL olmak zorunda: `1.2.0-rc.1` gibi
# on-surum etiketleri kabul edilmez. Gosterim surumu (AppVersion, kurucu adi)
# tam etiketi tasir; kaynak surumu yalniz ucluyu.
if ($Surum -match '^([0-9]+\.[0-9]+\.[0-9]+)') {
    $SayisalSurum = $Matches[1]
} else {
    throw ('gecersiz surum: ' + $Surum + '  (beklenen: 1.2.0 ya da 1.2.0-rc.1)')
}

# ── ISCC yolu ──────────────────────────────────────────────────────────────
if (-not $Iscc) { $Iscc = $env:FILLERCUT_ISCC }
if (-not $Iscc) {
    $adaylar = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    $Iscc = $adaylar | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path $Iscc)) {
    throw ('ISCC.exe bulunamadi. -Iscc ile yol verin ya da FILLERCUT_ISCC ' +
           'ortam degiskenini kurun (winget install JRSoftware.InnoSetup).')
}
Write-Host "Filler-Cut $Surum (kaynak surumu $SayisalSurum) · ISCC: $Iscc" -ForegroundColor Cyan

# ── 1) exe build ───────────────────────────────────────────────────────────
$DistDir = Join-Path $Kok 'dist\fillercut'
if ($SkipExeBuild) {
    if (-not (Test-Path (Join-Path $DistDir 'fillercut-ui.exe'))) {
        throw ('-SkipExeBuild verildi ama artefakt yok: ' + $DistDir)
    }
    Write-Host 'exe build atlandi (-SkipExeBuild)' -ForegroundColor Yellow
} else {
    Write-Host "`n[1/3] exe build" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'build_exe.ps1')
}

# ── 2) WebView2 bootstrapper ───────────────────────────────────────────────
# Kurucuya GOMULUR (Microsoft yeniden dagitima acikca izin verir). Kayit
# packaging\webview2.json: url + sha256 + boyut + Authenticode imzalayan.
# Hash TUTMAZSA build DURUR — Microsoft stub'i tazelemis demektir; yeni
# dosyayi indirip imzasini dogrulayip kaydi guncellemek gerekir.
Write-Host "`n[2/3] WebView2 bootstrapper" -ForegroundColor Cyan
$Wv2Dir = Join-Path $Kok 'build\webview2'
$Wv2Exe = Join-Path $Wv2Dir 'MicrosoftEdgeWebview2Setup.exe'
Invoke-Yerel 'WebView2 bootstrapper indirme/dogrulama' {
    & $Python (Join-Path $Kok 'packaging\webview2_indir.py') $Wv2Dir
}

# ── 3) ISCC ────────────────────────────────────────────────────────────────
Write-Host "`n[3/3] Inno Setup derlemesi" -ForegroundColor Cyan
$SetupDir = Join-Path $Kok 'dist_setup'
if (Test-Path $SetupDir) { Remove-Item $SetupDir -Recurse -Force }
$Iss = Join-Path $Kok 'packaging\fillercut.iss'
Invoke-Yerel 'ISCC derlemesi' {
    & $Iscc "/DSurum=$Surum" "/DSayisalSurum=$SayisalSurum" "/DDistDir=$DistDir" `
        "/DWebview2Setup=$Wv2Exe" "/O$SetupDir" $Iss
}

$Kurucu = Get-ChildItem $SetupDir -Filter '*.exe' | Select-Object -First 1
if (-not $Kurucu) { throw 'kurucu uretilmedi' }
Write-Host ''
Write-Host 'Kurucu hazir:' -ForegroundColor Green
Write-Host ("  {0}" -f $Kurucu.FullName)
Write-Host ("  boyut : {0:N1} MB" -f ($Kurucu.Length / 1MB))
Write-Host ("  surum : {0}" -f $Kurucu.VersionInfo.ProductVersion)
