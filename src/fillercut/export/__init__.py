"""Dışa aktarım katmanı — PLAN çıktısının RENDER'a girmeyen kolları.

İki çıktı burada yaşar:

* ``fcp7`` — kesim planından FCP7 (xmeml) proje dosyası: Premiere/Resolve
  köprüsü. RENDER'a hiç girmez, encode yoktur; üretilen şey saf metadata'dır.
* ``srt`` — transkriptten standart altyazı dosyası.

Katman sözleşmesi ``render/`` ile aynıdır: karar veren katman (PLAN) ile
uygulayan katman ayrıdır — buradaki modüller planı YORUMLAMAZ, yalnız başka
bir biçimde yazarlar (DESIGN.md §2).

``plan.json`` diske yazılmaz invariant'ı bu paketi KAPSAMAZ: XML ve SRT
kullanıcı çıktılarıdır, ara veri değil.
"""
