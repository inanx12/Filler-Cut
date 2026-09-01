"""İlk-çalıştırma kurulum katmanı (v1.2 Faz 2 — dağıtım epic'i).

Paketlenmiş Filler-Cut'ın whispercpp yolu iki sistem bağımlılığı ister:
Vulkan `whisper-cli` ikilisi ve bir GGML modeli. v1.1'e kadar ikisini de
kullanıcı elle kurup `filler-cut.toml`'a yazıyordu. Bu katman onları
indirilebilir hale getirir.

Modüller:

* ``yollar`` — hedef dizinler, sihirbazın yazdığı ayar ve **çözümleme
  önceliği** (mevcut kurulumlar sihirbazı hiç görmemeli).
* ``indir`` — akışlı, resume'lu, SHA-256 doğrulamalı indirme motoru.

Katman pipeline'a DOKUNMAZ: 6 aşama, review işlevleri, plan/detect mantığı
ve `plan.json` invariant'ları bu fazda değişmedi.
"""
