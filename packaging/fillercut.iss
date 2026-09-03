; Filler-Cut kurucusu — Inno Setup 6 (v1.2 Faz 4)
;
; Derleme: scripts\build_setup.ps1 (ISCC yolunu parametre/ortamdan alir).
; Elle:
;   ISCC.exe /DSurum=1.1.0 /DDistDir=..\dist\fillercut packaging\fillercut.iss
;
; PER-USER kurulum: PrivilegesRequired=lowest. Gerekce — exe'ler IMZASIZ
; (Faz 3 kabul edilmis risk); admin istemek SmartScreen uyarisinin ustune
; bir de UAC yukseltme diyalogu koyardi. Per-user kurulum ikisinden birini
; siler ve %LOCALAPPDATA%\Programs zaten kullanici yazilabilir.
;
; KALDIRMA SOZU (kritik): kurulum dizini tamamen silinir ama
; %LOCALAPPDATA%\fillercut (indirilen ikili + ~570 MB model) ve
; %APPDATA%\fillercut (ayar) KORUNUR. Kaldirici bunlari silmeyi sorar,
; varsayilan HAYIR — 570 MB'i kazara sildirmek kabul edilemez.

#ifndef Surum
  #define Surum "0.0.0"
#endif
#ifndef SayisalSurum
  ; VersionInfoVersion SAYISAL olmak zorunda: `1.2.0-rc.1` gibi on-surum
  ; etiketleri ISCC'de kabul edilmez. Gosterim surumu (AppVersion) tam
  ; etiketi tasir, kaynak surumu yalniz ucluyu.
  #define SayisalSurum "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\fillercut"
#endif
#ifndef Webview2Setup
  #define Webview2Setup "..\build\webview2\MicrosoftEdgeWebview2Setup.exe"
#endif

#define AppAdi "Filler-Cut"
#define Yayinci "Inan Esen"
#define AppUrl "https://github.com/inanx12/Filler-Cut"
#define UiExe "fillercut-ui.exe"
#define CliExe "fillercut.exe"

[Setup]
; AppId SABITTIR — upgrade Inno'nun kendi mekanizmasiyla bu GUID uzerinden
; yurur. DEGISTIRME: degisirse eski surum kaldirilmaz, yan yana iki kayit olur.
AppId={{7E588CAC-CFA7-42FB-B0AB-A4C9B51488A8}
AppName={#AppAdi}
AppVersion={#Surum}
AppVerName={#AppAdi} {#Surum}
AppPublisher={#Yayinci}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#SayisalSurum}
DefaultDirName={localappdata}\Programs\Filler-Cut
DefaultGroupName={#AppAdi}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
InfoBeforeFile=THIRD_PARTY_NOTICES.md
OutputDir=..\dist_setup
OutputBaseFilename=Filler-Cut-Setup-{#Surum}
SetupIconFile=fillercut.ico
UninstallDisplayIcon={app}\{#UiExe}
UninstallDisplayName={#AppAdi} {#Surum}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Kurulum dizini kullanicinin kendi profilinde; "her kullanici icin" secenegi
; yok, o yuzden yonetici modu diyalogunu hic gostermiyoruz.
UsedUserAreasWarning=no

[Languages]
Name: "turkce"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Masaustu kisayolu VARSAYILAN KAPALI (unchecked): Windows 11'de birincil
; yuzey Baslat Menusu/arama; masaustunu doldurmak yaygin bir sikayet.
; Isteyen kutuyu isaretler.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; YUKSELTME TEMIZLIGI (KI-15) — OLCULDU (1.2.2 -> 1.2.3 provasi).
; Inno dosyalari UZERINE yazar, ARTIK OLMAYANLARI SILMEZ. PyInstaller onedir
; bundle'i ise birlestirilecek bir agac degildir: eski surumden kalan her
; sey yeni bundle'in yaninda durmaya devam eder.
;
; Olculen sonuc: yukseltmeden sonra `_internal` altinda HEM
; `fillercut-1.2.2.dist-info` HEM `fillercut-1.2.3.dist-info` duruyordu.
; `importlib.metadata` ilk buldugunu doner, yani uygulama KENDI SURUMUNU
; 1.2.2 diye bildiriyordu — `--version`, `/api/instance` ve geri bildirim
; formundaki ortam blogu dahil. "Surumun tek dogruluk kaynagi" invariant'i
; kurulu makinede sessizce kirilmisti. Ayni sinif tehlike bayat `.pyd`/
; `.dll`lerde daha da kotudur (yanlis ikili yuklenir).
;
; KULLANICI VERISI ETKILENMEZ: modeller %LOCALAPPDATA%\fillercut, ayar
; %APPDATA%\fillercut altindadir; burada silinen yalniz uygulama bundle'i.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
; WebView2 bootstrapper yalniz calisma zamani EKSIKSE ayiklanir ve
; kurulum sonunda silinir (deleteafterinstall).
Source: "{#Webview2Setup}"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: WebView2Eksik

[Icons]
Name: "{autoprograms}\{#AppAdi}"; Filename: "{app}\{#UiExe}"; Comment: "Filler-Cut arayuzunu ac"
Name: "{autodesktop}\{#AppAdi}"; Filename: "{app}\{#UiExe}"; Tasks: desktopicon

[Run]
; Bootstrapper yalniz eksikse kosar. Argumanlar Microsoft'un kendi
; dokumanindan dogrulandi (webview2/concepts/distribution):
;   MicrosoftEdgeWebview2Setup.exe /silent /install
; Yukseltilmemis surecte per-user kurulum yapar — bizim kurucumuz da
; per-user oldugu icin tutarli.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  StatusMsg: "Microsoft Edge WebView2 kuruluyor..."; \
  Flags: waituntilterminated; Check: WebView2Eksik
Filename: "{app}\{#UiExe}"; Description: "{cm:LaunchProgram,{#AppAdi}}"; \
  Flags: nowait postinstall skipifsilent

[Code]
var
  FfmpegVarMi: Boolean;
  WebView2EksikBasladi: Boolean;

{ ---- WebView2 tespiti ------------------------------------------------------
  Ayni olcut `src/fillercut/web/native.py::webview2_var()` ile: .NET 4.6.2+
  VE dort EdgeUpdate kanalindan birinin `pv` ana surumu >= 86. Registry
  yollari Microsoft'un kendi dokumanindaki ile ayni (HKLM WOW6432Node +
  HKCU; 32-bit Windows'ta HKLM WOW'suz).

  Kurucu 32-bit calisir, o yuzden HKLM icin 64-bit gorunum ACIKCA istenir
  (HKLM64) — yoksa WOW6432Node yeniden yonlendirmesi yuzunden yanlis dala
  bakilir.                                                                  }

const
  WV2_RUNTIME = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WV2_BETA    = '{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}';
  WV2_DEV     = '{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}';
  WV2_CANARY  = '{65C35B14-6C1D-4122-AC46-7148CC9D6497}';
  NET462_RELEASE = 394802;
  WV2_MIN_ANA_SURUM = 86;

function AnaSurum(const Pv: String): Integer;
var
  P: Integer;
  Bas: String;
begin
  Result := -1;
  if Pv = '' then Exit;
  P := Pos('.', Pv);
  if P > 0 then Bas := Copy(Pv, 1, P - 1) else Bas := Pv;
  Result := StrToIntDef(Bas, -1);
end;

function PvYeterli(Kok: Integer; const Yol: String): Boolean;
var
  Pv: String;
begin
  Result := False;
  if RegQueryStringValue(Kok, Yol, 'pv', Pv) then
    Result := AnaSurum(Pv) >= WV2_MIN_ANA_SURUM;
end;

function KanalKurulu(const Guid: String): Boolean;
begin
  Result :=
    PvYeterli(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + Guid) or
    PvYeterli(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + Guid) or
    PvYeterli(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + Guid);
end;

function NetFrameworkYeterli(): Boolean;
var
  Release: Cardinal;
begin
  Result := False;
  if RegQueryDWordValue(HKLM64,
      'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release) then
    Result := Release >= NET462_RELEASE;
end;

function WebView2Kurulu(): Boolean;
begin
  Result := NetFrameworkYeterli() and
    (KanalKurulu(WV2_RUNTIME) or KanalKurulu(WV2_BETA) or
     KanalKurulu(WV2_DEV) or KanalKurulu(WV2_CANARY));
end;

function WebView2Eksik(): Boolean;
begin
  Result := not WebView2Kurulu();
end;

{ ---- ffmpeg tespiti -------------------------------------------------------
  PATH'te ffmpeg var mi? Kurulumu ENGELLEMEZ — uygulama zaten temiz Turkce
  hata veriyor (Faz 3'te paketlenmis exe'de dogrulandi). Yalniz kurulum
  sonunda bilgilendirme yapilir.                                            }

function FfmpegBul(): Boolean;
var
  Kod: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C ffmpeg -version >nul 2>&1', '',
                 SW_HIDE, ewWaitUntilTerminated, Kod) and (Kod = 0);
end;

function WingetVar(): Boolean;
var
  Kod: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C winget --version >nul 2>&1', '',
                 SW_HIDE, ewWaitUntilTerminated, Kod) and (Kod = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { WebView2'nin kurulum ONCESI durumu: bitis sayfasinda "denendi mi"
    sorusunu yanitlar. }
  if CurStep = ssInstall then
    WebView2EksikBasladi := WebView2Eksik();
  if CurStep = ssPostInstall then
    FfmpegVarMi := FfmpegBul();
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Mesaj: String;
begin
  if CurPageID <> wpFinished then Exit;

  Mesaj := '';
  { Cikis kodu yerine SONUC olculur: bootstrapper kostuktan sonra calisma
    zamani hala yoksa basarisiz olmustur. [Run] girdileri bu sayfadan ONCE
    kostugu icin buradaki kontrol kurulum sonrasi durumu gorur. Kurulum
    YARIDA BIRAKILMAZ — yalniz uyarilir (brief: net uyari + devam). }
  if WebView2EksikBasladi and WebView2Eksik() then
    Mesaj := Mesaj +
      'Uyari: Microsoft Edge WebView2 kurulamadi.' + #13#10 +
      'Filler-Cut yine calisir; arayuz kendi penceresi yerine varsayilan' + #13#10 +
      'tarayicinizda acilir.' + #13#10 +
      { ISPP tuzagi: satirin ILK karakteri '#' olursa preprocessor onu
        direktif sanar ("Unknown preprocessor directive") — Pascal yorumu
        icinde bile. Satir sonu sabitleri bu yuzden satir BASINA yazilmaz. }
      'Elle kurmak icin: https://developer.microsoft.com/microsoft-edge/webview2/' + #13#10 + #13#10;

  if not FfmpegVarMi then
  begin
    Mesaj := Mesaj +
      'ffmpeg bulunamadi. Filler-Cut video islemek icin ffmpeg''e ihtiyac' + #13#10 +
      'duyar ve onu dagitmaz (lisans gruplari ayri).' + #13#10;
    { winget yoksa (eski Win10) o yolu HIC gosterme — calismayacak bir komut
      onermek kullaniciyi ikinci bir hataya surukler. }
    if WingetVar() then
      Mesaj := Mesaj +
        'Kurmak icin komut satirinda:' + #13#10 +
        '    winget install ffmpeg' + #13#10 +
        'ya da elle: https://ffmpeg.org/download.html' + #13#10
    else
      Mesaj := Mesaj +
        'Kurulum: https://ffmpeg.org/download.html' + #13#10;
  end;

  if Mesaj <> '' then
    WizardForm.FinishedLabel.Caption :=
      WizardForm.FinishedLabel.Caption + #13#10#13#10 + Mesaj;
end;

{ ---- kaldirma -------------------------------------------------------------
  Kullanici verisi (indirilen ikili + model + ayar) kurulumdan BAGIMSIZ
  yasar. Varsayilan HAYIR: 570 MB'lik modeli kazara sildirmek, kullaniciyi
  yeniden indirmeye zorlar (Faz 2/3 notu).                                   }

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  VeriDizini, AyarDizini: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;

  VeriDizini := ExpandConstant('{localappdata}\fillercut');
  AyarDizini := ExpandConstant('{userappdata}\fillercut');

  if not (DirExists(VeriDizini) or DirExists(AyarDizini)) then Exit;

  if SuppressibleMsgBox(
       'Indirilen konusma modeli ve ayarlar bilgisayarinizda duruyor' + #13#10 +
       '(' + VeriDizini + ').' + #13#10#13#10 +
       'Bunlar da silinsin mi?' + #13#10 +
       'Hayir derseniz Filler-Cut''i yeniden kurdugunuzda tekrar' + #13#10 +
       'indirmeniz gerekmez.',
       mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
  begin
    DelTree(VeriDizini, True, True, True);
    DelTree(AyarDizini, True, True, True);
  end;
end;
