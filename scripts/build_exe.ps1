<#
.SYNOPSIS
    Filler-Cut Windows exe'lerini tek komutla üretir ve smoke test'i koşar.

.DESCRIPTION
    Repo kökünden çalıştırın:

        .\scripts\build_exe.ps1

    Sırayla: ön kontroller -> temiz dist/build -> PyInstaller (spec'ten) ->
    artefakt özeti -> `exe` marker'lı smoke testler.

    Çıktı: dist\fillercut\ (onedir) — fillercut.exe + fillercut-ui.exe.
    Karar gerekçesi: experiments\paketleme_spike\onedir_onefile.md

.PARAMETER Onefile
    Tek dosya (portable) varyantı üretir. DAĞITILAN biçim bu DEĞİLDİR
    (açılış +1.54 sn) — ölçüm/portable kullanım için bırakıldı.

.PARAMETER SkipTest
    Smoke testleri atlar (yalnız build).
#>
[CmdletBinding()]
param(
    [switch]$Onefile,
    [switch]$SkipTest
)

$ErrorActionPreference = 'Stop'

function Invoke-Yerel {
    <#
      Yerel (native) exe cagrisi + cikis kodu kontrolu.

      PowerShell 5.1'de `$ErrorActionPreference = 'Stop'` iken bir native
      komutun STDERR'e yazmasi terminating NativeCommandError uretir —
      PyInstaller ilerlemesini stderr'e bastigi icin build daha ilk satirda
      "hata" sayiliyordu (olculdu). Bu yuzden native cagri EAP='Continue'
      altinda kosar ve basari yalnizca cikis kodundan okunur.
    #>
    param([string]$Aciklama, [scriptblock]$Komut)
    $eski = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Komut } finally { $ErrorActionPreference = $eski }
    if ($LASTEXITCODE -ne 0) { throw ($Aciklama + ' basarisiz (kod ' + $LASTEXITCODE + ')') }
}

# Repo kökü: bu script <kök>\scripts\build_exe.ps1
$Kok = Split-Path -Parent $PSScriptRoot
Set-Location $Kok

$Python = Join-Path $Kok '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    throw ('venv bulunamadi: ' + $Python + '  (once: python -m venv .venv; pip install -e ".[dev]")')
}

# PyInstaller PIN'lidir (pyproject dev extra'si): ayni spec farkli surumde
# farkli bundle uretir, tekrarlanabilirlik o pin'e baglidir.
$eskiEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $Python -c "import PyInstaller"
$ErrorActionPreference = $eskiEAP
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller kurulu degil - pip install -e ".[dev]"'
}
# pywebview ON KONTROLU (KI-12) — DAGITIM ICIN ZORUNLU.
# Kurulu degilse PyInstaller onu bundle'a koyamaz; spec'teki webview hidden
# import'lari yalnizca "Hidden import not found!" WARNING'i uretir ve build
# YESIL biter. Ortaya cikan exe calisma aninda "pywebview kurulu degil" deyip
# tarayici fallback'ine duser: native pencere HIC acilmaz ve konsolsuz
# exe'de bu satir kullaniciya gorunmez. v1.2.0-v1.2.2 kuruculari boyle cikti
# (CI `pip install -e ".[dev]"` yapiyordu, `native` extra'si yoktu).
# Sessiz bozuk artefakt uretmektense BURADA durmak yegdir.
$ErrorActionPreference = 'Continue'
& $Python -c "import webview"
$ErrorActionPreference = $eskiEAP
if ($LASTEXITCODE -ne 0) {
    throw 'pywebview kurulu degil - native pencere bundle a GIRMEZ. Once: pip install -e ".[dev,native]"'
}

$PiSurum = (& $Python -m PyInstaller --version).Trim()
$FcSurum = (& $Python -c "from fillercut import __version__; print(__version__)").Trim()
$PwSurum = (& $Python -c "import importlib.metadata as m; print(m.version('pywebview'))").Trim()
Write-Host "Filler-Cut $FcSurum · PyInstaller $PiSurum · pywebview $PwSurum" -ForegroundColor Cyan

if ($Onefile) {
    $env:FILLERCUT_ONEFILE = '1'
    $DistYol = Join-Path $Kok 'dist_onefile'
    $WorkYol = Join-Path $Kok 'build_onefile'
    Write-Host "kip: ONEFILE (dagitilan bicim DEGIL)" -ForegroundColor Yellow
} else {
    Remove-Item Env:\FILLERCUT_ONEFILE -ErrorAction SilentlyContinue
    $DistYol = Join-Path $Kok 'dist'
    $WorkYol = Join-Path $Kok 'build'
    Write-Host "kip: onedir" -ForegroundColor Cyan
}

# Temiz build: bayat bir bundle'in "calisiyor" gorunmesi bu fazin en pahali
# yanlisi olurdu (spec'ten dusen bir veri dosyasi eski dist'te durmaya
# devam eder).
foreach ($d in @($DistYol, $WorkYol)) {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
}

$Spec = Join-Path $Kok 'packaging\fillercut.spec'
Invoke-Yerel 'PyInstaller build' {
    & $Python -m PyInstaller $Spec --noconfirm --clean --distpath $DistYol --workpath $WorkYol
}

# ── artefakt ozeti ─────────────────────────────────────────────────────────
$Kok2 = if ($Onefile) { $DistYol } else { Join-Path $DistYol 'fillercut' }
$Dosyalar = Get-ChildItem $Kok2 -Recurse -File
$Bayt = ($Dosyalar | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "Artefakt: $Kok2" -ForegroundColor Green
Write-Host ("  boyut : {0:N0} MB" -f ($Bayt / 1MB))
Write-Host ("  dosya : {0}" -f $Dosyalar.Count)
foreach ($e in (Get-ChildItem $Kok2 -Filter *.exe)) {
    $vi = $e.VersionInfo
    Write-Host ("  exe   : {0}  ({1:N1} MB, {2} {3})" -f $e.Name, ($e.Length / 1MB), $vi.ProductName, $vi.ProductVersion)
}

if ($SkipTest) {
    Write-Host "`nSmoke testler atlandi (-SkipTest)." -ForegroundColor Yellow
    exit 0
}
if ($Onefile) {
    Write-Host "`nSmoke testler onedir artefaktina bakar; onefile kipinde atlandi." -ForegroundColor Yellow
    exit 0
}

Write-Host "`nSmoke testler (-m exe):" -ForegroundColor Cyan
Invoke-Yerel 'Smoke test' { & $Python -m pytest tests/test_paketleme.py -m exe -q }
Write-Host "`nHazir." -ForegroundColor Green
